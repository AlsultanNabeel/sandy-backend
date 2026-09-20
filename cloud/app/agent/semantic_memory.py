"""Semantic memory on top of MongoDB + OpenAI embeddings.

Collections:
  sandy_facts             user facts, including the indexed life lists
  sandy_memories          conversation summaries (read here, written by graph.py)

Every doc has a chat_id. Facts go through the enforced
``tenant_db.scoped(..., field="chat_id")`` wrapper — the same isolation-by-
construction boundary as every other store — so a forgotten filter can't leak
across tenants. Every authenticated (non-guest) user reads and writes their
own memory; guests and unauthenticated get nothing.

``$vectorSearch`` is the one exception: Atlas requires it to be pipeline stage
one, which the wrapper's auto-``$match`` would break, so that path filters
inside the ``$vectorSearch`` stage itself (sourcing the tenant id from the
scoped collection's ``.tenant``, not a separately-derived value) and runs
against the raw collection.

Legacy docs (no chat_id, or tagged with one of the owner's old identities) are
reconciled onto his canonical tenant id by
``app.utils.user_profiles.reconcile_owner_identity``, called once at boot.

Search tries, in order:
  1. Atlas $vectorSearch (semantic, needs the vector index)
  2. $text search (keyword fallback)
  3. sort by usage_count / ts (last resort if there's no text index either)

Call init_mongo_memory(...) once at startup. Embeddings prefer Azure when an
embedding deployment is configured, else fall back to the direct OpenAI key.
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

from pymongo.errors import PyMongoError

from app.db import configure, get_db
from app.utils.tenant_db import scoped
from app.utils.user_profiles import active_profile_is_guest, get_active_user_profile

logger = logging.getLogger(__name__)

# Warn only once per process when vector search degrades to keyword sort.
_vector_search_warned = False

# Client used for embeddings (Azure or direct OpenAI) and the model/deployment
# name to pass it. Set in init_mongo_memory.
_embed_client = None
_embed_model = "text-embedding-3-small"

# **A deadline on the embedding call.**
#
# There was none, and the OpenAI SDK's default is ten minutes with retries. This
# call runs on the soul pool, which a request waits on for three seconds and then
# abandons — but abandoning returns the *caller*, never the worker. A stalled
# embeddings endpoint therefore holds pool workers for minutes while every new
# turn queues more work behind them, and once all of them are held, every user
# on that dyno gets a Sandy who does not know their name. The timeout is what
# makes the worker come back.
_EMBED_TIMEOUT_S = 8.0

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMS = 1536
_VECTOR_INDEX = "sandy_vector_index"


# Profile helpers


def _facts_coll():
    return scoped(get_db(), "sandy_facts", field="chat_id")


def _can_write_memory() -> bool:
    """Any authenticated (non-guest) tenant may write their own memory.

    ``relation`` used to be "owner"/"family" under the old single-household
    model; ``build_user_profile`` (every REST + agent request today) only ever
    sets "user"/"guest", so this must key off the same guest check every other
    store uses, not the stale relation strings.
    """
    profile = get_active_user_profile()
    if not profile:
        return False
    return not active_profile_is_guest()


def _can_read_memory() -> bool:
    """Same rule as write: only non-guest (authenticated) tenants read memory."""
    return _can_write_memory()


# Init


def init_mongo_memory(
    mongo_db,
    openai_client=None,
    azure_client=None,
    azure_embedding_deployment="",
) -> None:
    """Store the MongoDB and embedding handles, build indexes, migrate legacy docs.

    Embeddings prefer Azure when ``azure_client`` and ``azure_embedding_deployment``
    are both given (deploy text-embedding-3-small to keep the 1536-dim index
    valid); otherwise they fall back to the direct ``openai_client``.
    """
    global _embed_client, _embed_model
    configure(mongo_db)

    if azure_client is not None and azure_embedding_deployment:
        _embed_client = azure_client
        _embed_model = azure_embedding_deployment
    else:
        _embed_client = openai_client
        _embed_model = _EMBEDDING_MODEL

    if mongo_db is None:
        logger.warning("[Memory] no MongoDB, memory storage disabled")
        return

    try:
        mongo_db["sandy_facts"].create_index(
            [("chat_id", 1), ("text", "text")],
            default_language="none",
            background=True,
        )
        mongo_db["sandy_facts"].create_index([("chat_id", 1)], background=True)
    except Exception as e:
        logger.warning("[Memory] index setup: %s", e)

    mode = "vector + keyword" if _embed_client else "keyword only"
    logger.info("[Memory] MongoDB memory ready (%s)", mode)


# Embeddings


def _importance_score(usage_count: int, created_at=None) -> float:
    """Usage count weighted by recency, decaying to near zero over a year."""
    from datetime import datetime, timezone
    recency = 1.0
    if created_at is not None:
        now = datetime.now(timezone.utc)
        if getattr(created_at, "tzinfo", None) is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - created_at).days)
        recency = max(0.1, 1.0 - age_days / 365.0)
    return (usage_count + 1) * recency


def _bump_usage_later(coll, results: List[Dict]) -> None:
    """Record that these facts were used, off the request path.

    A ranking counter that changes nothing about this reply, or the next one, is
    not worth a write the user waits for. The values are read out here — the
    background job must not re-read the documents, or it pays back the round
    trips it was written to remove.
    """
    updates = [
        (r["_id"], _importance_score((r.get("usage_count") or 0) + 1,
                                     r.get("created_at")))
        for r in results if r.get("_id") is not None
    ]
    if not updates:
        return

    def _apply() -> None:
        for doc_id, score in updates:
            try:
                coll.update_one(
                    {"_id": doc_id},
                    {"$inc": {"usage_count": 1}, "$set": {"importance_score": score}},
                )
            except PyMongoError:
                logger.debug("[chroma] usage bump skipped", exc_info=True)

    from app.utils.thread_pool import submit_background

    submit_background(_apply, _label="facts-usage")


def _embed(text: str) -> Optional[List[float]]:
    """Embed text, or None if there's no client or the call fails."""
    if _embed_client is None or not text:
        return None
    vectors = _embed_many([text])
    return vectors[0] if vectors else None


def _embed_many(texts: List[str]) -> List[Optional[List[float]]]:
    """Embed a batch in **one** request, in order, with None for any failure.

    The embeddings endpoint has always taken a list; we were calling it once per
    item inside a `for` loop. Indexing a person's life — their books, habits,
    tasks and journal — is the caller that made that visible: a hundred items was
    a hundred sequential HTTPS round trips, which is not slow, it is a stall.

    One call for the whole batch is the same tokens and the same price. The only
    thing it removes is the waiting.
    """
    if _embed_client is None or not texts:
        return [None] * len(texts)
    try:
        resp = _embed_client.embeddings.create(
            model=_embed_model, input=texts, timeout=_EMBED_TIMEOUT_S)
        # `data` is ordered by the API, but it carries an explicit `index` and
        # relying on the order rather than on the field is how a batch silently
        # attaches the wrong vector to the wrong text — a failure with no symptom
        # except that recall stops making sense.
        out: List[Optional[List[float]]] = [None] * len(texts)
        for item in resp.data:
            idx = getattr(item, "index", None)
            if isinstance(idx, int) and 0 <= idx < len(out):
                out[idx] = item.embedding
        return out
    except Exception as e:
        logger.warning("[Memory] batch embedding failed (%d texts): %s", len(texts), e)
        return [None] * len(texts)


# ID helpers


def _fact_id(text: str, chat_id: str = "") -> str:
    """ID scoped to a user, so the same text under two users gets two IDs."""
    return (
        "f_"
        + hashlib.sha1(f"{chat_id}:{text}".encode(), usedforsecurity=False).hexdigest()[
            :20
        ]
    )


# Facts


def load_facts_to_chroma(facts: List[Dict[str, Any]]) -> None:
    """Upsert user facts, embedding the new ones.

    **Three round trips at most, whatever the size of the batch, and none at all
    when nothing is new.**

    This used to run per item: one `count_documents` to ask whether it existed,
    one embedding request if not, one `update_one` to store it. For a person with
    a hundred books, habits, tasks and journal entries that is a hundred database
    queries and up to a hundred sequential calls to the embeddings API — and its
    caller (`life_snapshot.index_life_for_search`) sits on a path that runs on
    every message. The steady state is the worst part: once everything is
    indexed, the work is *entirely* the hundred existence checks, every single
    turn, to discover that there is nothing to do.

    Now: one query to find which ids already exist, one batched embedding call
    for the genuinely new ones (plus any stored earlier without a vector), one
    bulk write. Nothing new means one query and then nothing, which is what a
    no-op should cost.
    """
    if not _can_write_memory():
        return
    coll = _facts_coll()
    if coll is None or not facts:
        return
    chat_id = coll.tenant

    # De-duplicate within the batch too: the same text twice would otherwise
    # embed twice and race itself in the bulk write.
    wanted: Dict[str, Dict[str, Any]] = {}
    for fact in facts:
        text = (fact.get("text") or "").strip()
        if not text:
            continue
        wanted.setdefault(_fact_id(text, chat_id), {
            "text": text,
            "type": fact.get("type", "general"),
        })
    if not wanted:
        return

    try:
        # `$slice: 1` keeps the payload to one float per fact while still
        # telling us which stored facts have no vector yet.
        found = list(coll.find({"_id": {"$in": list(wanted)}},
                               {"_id": 1, "embedding": {"$slice": 1}}))
    except PyMongoError as exc:
        logger.warning("[Memory] load_facts existence check failed: %s", exc)
        return
    existing = {d["_id"] for d in found}
    # A fact stored while the embeddings endpoint was down has no vector and
    # would stay keyword-only forever; retry those whenever embedding is on.
    unembedded = ([d["_id"] for d in found if not d.get("embedding")]
                  if _embed_client is not None else [])

    new_ids = [fid for fid in wanted if fid not in existing]
    if not new_ids and not unembedded:
        return

    vectors = _embed_many([wanted[fid]["text"] for fid in new_ids + unembedded])
    for fid, vec in zip(unembedded, vectors[len(new_ids):]):
        if vec:
            try:
                coll.update_one({"_id": fid}, {"$set": {"embedding": vec}})
            except PyMongoError as exc:
                logger.warning("[Memory] embedding backfill failed: %s", exc)
    vectors = vectors[:len(new_ids)]
    if not new_ids:
        return

    docs: List[Dict[str, Any]] = []
    for fid, vec in zip(new_ids, vectors):
        doc: Dict[str, Any] = {
            "_id": fid,
            "text": wanted[fid]["text"],
            "type": wanted[fid]["type"],
            "usage_count": 0,
            "importance_score": 1.0,
        }
        if vec:
            doc["embedding"] = vec
        docs.append(doc)

    try:
        inserted = coll.insert_missing(docs)
    except PyMongoError as exc:
        logger.warning("[Memory] load_facts bulk write failed: %s", exc)
        return
    if inserted:
        logger.info("[Memory] indexed %d new facts (chat_id=%s)", inserted, chat_id)


# Search


def _vector_search(
    col, query: str, chat_id: str, n_results: int, extra_project: Dict,
    query_vector: Optional[List[float]] = None,
    post_match: Optional[Dict[str, Any]] = None,
    embedded: bool = False,
) -> Optional[List[Dict]]:
    """$vectorSearch filtered by chat_id, or None if it can't run.

    `query_vector` lets a caller that is about to run more than one search over
    the same string pay for the embedding once — see `search_memory_for_turn`.

    `post_match` narrows further on fields the Atlas index does not declare as
    filters (adding one there is an index rebuild). It runs after the search, so
    the search over-fetches to leave enough behind.

    `embedded=True` says the caller already tried to embed this query: a
    missing `query_vector` then means the embedding *failed*, and asking the
    endpoint again for the same string would only add another timeout.
    """
    vec = query_vector if (query_vector or embedded) else _embed(query)
    if not vec:
        return None
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": _VECTOR_INDEX,
                    "path": "embedding",
                    "queryVector": vec,
                    "numCandidates": n_results * 20 if post_match else n_results * 10,
                    "limit": n_results * 5 if post_match else n_results,
                    "filter": {"chat_id": {"$eq": chat_id}},
                }
            },
            *([{"$match": post_match}, {"$limit": n_results}] if post_match else []),
            {
                "$project": {
                    "text": 1,
                    "score": {"$meta": "vectorSearchScore"},
                    **extra_project,
                }
            },
        ]
        return list(col.aggregate(pipeline))
    except Exception as exc:
        global _vector_search_warned
        if not _vector_search_warned:
            logger.warning(
                "[chroma] vector search failed, falling back to keyword sort: %s", exc
            )
            _vector_search_warned = True
        return None


def search_relevant_facts(query: str, n_results: int = 5,
        query_vector: Optional[List[float]] = None,
        embedded: bool = False) -> List[str]:
    """Semantic search over the current user's facts.

    `embedded` — see `_vector_search`.
    """
    if not _can_read_memory():
        return []
    coll = _facts_coll()
    if coll is None:
        return []
    chat_id = coll.tenant
    try:
        # The emptiness check exists to spare an embedding call for a user
        # with no facts. Once the query is embedded it saves nothing — an empty
        # collection answers the search with nothing just as well — and it was
        # one more serial round trip on every turn.
        if not (query_vector or embedded) and coll.count_documents({}) == 0:
            return []

        # $vectorSearch must be pipeline stage one (Atlas requirement), so it
        # runs against the raw collection with the tenant filter built in —
        # the wrapper's auto-$match can't be used here.
        results = _vector_search(
            get_db()["sandy_facts"], query, chat_id, n_results,
            {"usage_count": 1, "created_at": 1}, query_vector, embedded=embedded,
        )

        if results is None:
            try:
                results = list(
                    coll.find(
                        {"$text": {"$search": query}},
                        {"score": {"$meta": "textScore"}, "text": 1, "usage_count": 1, "created_at": 1},
                    )
                    .sort([("score", {"$meta": "textScore"})])
                    .limit(n_results)
                )
            except Exception:
                results = list(
                    coll.find({}, {"text": 1, "usage_count": 1, "created_at": 1})
                    .sort("importance_score", -1)
                    .limit(n_results)
                )

        # الترتيب بيتحدّث بالخلفية.
        #
        # كان `update_one` لكل نتيجة على مسار الطلب — خمس كتبات بكل رسالة
        # عشان عدّاد ترتيب ما بيغيّر ردّ هالدور ولا الدور اللي بعده. المستخدم
        # كان يستنّاهن. صاروا يتنفّذوا بعد ما يمشي الردّ، وبيحملوا المستأجر
        # معهن (`submit_background` بينسخ السياق).
        if results:
            _bump_usage_later(coll, results)
        return [r["text"] for r in results if r.get("text")]
    except Exception as e:
        logger.warning("[Memory] search_relevant_facts: %s", e)
        return []


def search_relevant_summaries(query: str, thread_id: str, n_results: int = 3,
                              query_vector: Optional[List[float]] = None,
                              embedded: bool = False) -> List[str]:
    """Semantic search over this user's summaries of one conversation thread.

    The tenant comes from the context (the summaries' ``chat_id`` is the user);
    ``thread_id`` picks the conversation. It used to be the other way round —
    the client-supplied conversation id was the only filter, so two accounts
    using the same id read each other's summaries.
    """
    if not _can_read_memory():
        return []
    coll = scoped(get_db(), "sandy_memories", field="chat_id", bump=False)
    if coll is None or not thread_id:
        return []
    match = {"label": "conversation_summary", "thread_id": str(thread_id)}
    try:
        # `summary` has to be asked for: `_vector_search` projects only `text`,
        # `score` and what it is handed, and summaries live in `summary`.
        results = _vector_search(get_db()["sandy_memories"], query, coll.tenant,
                                 n_results, {"summary": 1}, query_vector,
                                 post_match=match, embedded=embedded)
        if results is None:
            results = list(coll.find(match, {"summary": 1})
                           .sort("created_at", -1).limit(n_results))
        return [r["summary"] for r in results if r.get("summary")]
    except Exception as exc:
        logger.warning("[chroma] search_relevant_summaries failed: %s", exc)
        return []


def migrate_summary_threads(mongo_db) -> None:
    """Boot-time, idempotent: move old summaries onto their user.

    Summaries written before the fix carry the thread in ``chat_id`` and the
    user in ``user_id``. Rewrite them to ``chat_id=user_id`` and keep the thread
    as ``thread_id``, so the new reader (and account deletion) finds them.
    """
    if mongo_db is None:
        return
    try:
        res = mongo_db["sandy_memories"].update_many(
            {"label": "conversation_summary", "thread_id": {"$exists": False},
             "user_id": {"$nin": [None, ""]}},
            [{"$set": {"thread_id": "$chat_id", "chat_id": "$user_id"}}],
        )
        if res.modified_count:
            logger.info("[Memory] moved %d summaries onto their user", res.modified_count)
    except PyMongoError as exc:
        logger.warning("[Memory] summary thread migration failed: %s", exc)


def search_memory_for_turn(
    query: str,
    summary_thread: str,
    n_facts: int = 5,
    n_summaries: int = 3,
) -> Dict[str, List[str]]:
    """Both semantic lookups a turn needs, over one embedding of the query.

    They used to be two jobs on the soul pool, and each embedded the *same
    string* on its own: two OpenAI round trips per message for one query, every
    message, on chat and on voice. Embedding once and handing the vector to both
    halves that, and the two Mongo aggregates that now run in sequence cost far
    less than the request they replace.

    Returns `{"summaries": [...], "facts": [...]}`; either list is empty when
    that layer has nothing or is not configured, exactly as before.
    """
    vec = _embed(query) if query else None
    return {
        "summaries": search_relevant_summaries(
            query, summary_thread, n_results=n_summaries, query_vector=vec,
            embedded=True),
        "facts": search_relevant_facts(query, n_results=n_facts, query_vector=vec,
                                       embedded=True),
    }


def semantic_memory_stats() -> Dict[str, Any]:
    """Return counts for the current user, for health checks and debugging."""
    if not _can_read_memory():
        return {"path": "mongodb", "facts": 0}
    facts_count = 0
    facts_coll = _facts_coll()
    if facts_coll is not None:
        try:
            facts_count = facts_coll.count_documents({})
        except PyMongoError:
            logger.warning("[Memory] facts count failed", exc_info=True)
    return {
        "path": "mongodb",
        "vector_search": _embed_client is not None,
        "facts": facts_count,
    }


__all__ = [
    "init_mongo_memory",
    "load_facts_to_chroma",
    "search_relevant_facts",
    "search_relevant_summaries",
    "search_memory_for_turn",
    "semantic_memory_stats",
]
