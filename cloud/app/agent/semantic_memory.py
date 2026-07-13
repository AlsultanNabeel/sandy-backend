"""Semantic memory on top of MongoDB + OpenAI embeddings.

Collections:
  sandy_facts             user facts from the learning system
  sandy_conversations     recent (user, assistant) turns
  sandy_context_metadata  per-turn topic tracking

Every doc has a chat_id. Facts/conversations go through the enforced
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

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMS = 1536
_VECTOR_INDEX = "sandy_vector_index"


# Profile helpers


def _facts_coll():
    return scoped(get_db(), "sandy_facts", field="chat_id")


def _convs_coll():
    return scoped(get_db(), "sandy_conversations", field="chat_id")


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
        mongo_db["sandy_conversations"].create_index(
            [("chat_id", 1), ("text", "text")],
            default_language="none",
            background=True,
        )
        mongo_db["sandy_facts"].create_index([("chat_id", 1)], background=True)
        mongo_db["sandy_conversations"].create_index([("chat_id", 1)], background=True)
        mongo_db["sandy_context_metadata"].create_index(
            [("timestamp", -1)],
            background=True,
        )
    except Exception as e:
        logger.warning(f"[Memory] index setup: {e}")

    mode = "vector + keyword" if _embed_client else "keyword only"
    logger.info(f"[Memory] MongoDB memory ready ({mode})")


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


def _embed(text: str) -> Optional[List[float]]:
    """Embed text, or None if there's no client or the call fails."""
    if _embed_client is None or not text:
        return None
    try:
        resp = _embed_client.embeddings.create(
            model=_embed_model,
            input=text,
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.warning(f"[Memory] embedding failed: {e}")
        return None


# ID helpers


def _fact_id(text: str, chat_id: str = "") -> str:
    """ID scoped to a user, so the same text under two users gets two IDs."""
    return (
        "f_"
        + hashlib.sha1(f"{chat_id}:{text}".encode(), usedforsecurity=False).hexdigest()[
            :20
        ]
    )


def _conv_id(user_text: str, assistant_text: str, chat_id: str = "") -> str:
    combined = f"{chat_id}:{user_text}||{assistant_text}"
    return (
        "c_" + hashlib.sha1(combined.encode(), usedforsecurity=False).hexdigest()[:20]
    )


# Facts


def load_facts_to_chroma(facts: List[Dict[str, Any]]) -> None:
    """Upsert user facts, embedding the new ones."""
    if not _can_write_memory():
        return
    coll = _facts_coll()
    if coll is None or not facts:
        return
    chat_id = coll.tenant
    inserted = 0
    for fact in facts:
        text = (fact.get("text") or "").strip()
        if not text:
            continue
        fid = _fact_id(text, chat_id)
        try:
            if coll.count_documents({"_id": fid}) > 0:
                continue
            doc = {
                "_id": fid,
                "text": text,
                "type": fact.get("type", "general"),
                "usage_count": 0,
                "importance_score": 1.0,
            }
            vec = _embed(text)
            if vec:
                doc["embedding"] = vec
            # chat_id isn't in `doc` — the scoped upsert seeds it from the
            # filter's equality terms, so it can't drift from the tenant.
            result = coll.update_one(
                {"_id": fid},
                {"$setOnInsert": doc},
                upsert=True,
            )
            if result.upserted_id is not None:
                inserted += 1
        except Exception as e:
            logger.warning(f"[Memory] load_facts: {e}")
    if inserted:
        logger.info(
            f"[Memory] indexed {inserted} new facts (chat_id={chat_id})", flush=True
        )


# Conversations


def load_conversations_to_chroma(
    conversations: List[Dict[str, Any]], max_recent: int = 60
) -> None:
    """Upsert recent conversation turns, embedding the new ones."""
    if not _can_write_memory():
        return
    coll = _convs_coll()
    if coll is None or not conversations:
        return
    chat_id = coll.tenant
    recent = conversations[-max_recent:]
    inserted = 0
    for conv in recent:
        user_text = (conv.get("user") or conv.get("content") or "").strip()
        asst_text = (conv.get("sandy") or conv.get("assistant") or "").strip()
        if not user_text:
            continue
        combined = f"المستخدم: {user_text}"
        if asst_text:
            combined += f"\nساندي: {asst_text}"
        cid = _conv_id(user_text, asst_text, chat_id)
        try:
            if coll.count_documents({"_id": cid}) > 0:
                continue
            doc = {
                "_id": cid,
                "text": combined,
                "role": "conversation",
                "ts": conv.get("timestamp", ""),
            }
            vec = _embed(combined)
            if vec:
                doc["embedding"] = vec
            # chat_id isn't in `doc` — the scoped upsert seeds it from the
            # filter's equality terms, so it can't drift from the tenant.
            result = coll.update_one(
                {"_id": cid},
                {"$setOnInsert": doc},
                upsert=True,
            )
            if result.upserted_id is not None:
                inserted += 1
        except Exception as e:
            logger.warning(f"[Memory] load_conversations: {e}")
    if inserted:
        logger.info(
            f"[Memory] indexed {inserted} new conversation turns (chat_id={chat_id})",
            flush=True,
        )


# Search


def _vector_search(
    col, query: str, chat_id: str, n_results: int, extra_project: Dict
) -> Optional[List[Dict]]:
    """$vectorSearch filtered by chat_id, or None if it can't run."""
    vec = _embed(query)
    if not vec:
        return None
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": _VECTOR_INDEX,
                    "path": "embedding",
                    "queryVector": vec,
                    "numCandidates": n_results * 10,
                    "limit": n_results,
                    "filter": {"chat_id": {"$eq": chat_id}},
                }
            },
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


def search_relevant_facts(query: str, n_results: int = 5) -> List[str]:
    """Semantic search over the current user's facts."""
    if not _can_read_memory():
        return []
    coll = _facts_coll()
    if coll is None:
        return []
    chat_id = coll.tenant
    try:
        if coll.count_documents({}) == 0:
            return []

        # $vectorSearch must be pipeline stage one (Atlas requirement), so it
        # runs against the raw collection with the tenant filter built in —
        # the wrapper's auto-$match can't be used here.
        results = _vector_search(
            get_db()["sandy_facts"], query, chat_id, n_results,
            {"usage_count": 1, "created_at": 1},
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

        if results:
            for r in results:
                new_usage = (r.get("usage_count") or 0) + 1
                score = _importance_score(new_usage, r.get("created_at"))
                coll.update_one(
                    {"_id": r["_id"]},
                    {"$inc": {"usage_count": 1}, "$set": {"importance_score": score}},
                )
        return [r["text"] for r in results if r.get("text")]
    except Exception as e:
        logger.warning(f"[Memory] search_relevant_facts: {e}")
        return []


def search_relevant_conversations(query: str, n_results: int = 3) -> List[str]:
    """Semantic search over the current user's conversation turns."""
    if not _can_read_memory():
        return []
    coll = _convs_coll()
    if coll is None:
        return []
    chat_id = coll.tenant
    try:
        if coll.count_documents({}) == 0:
            return []

        results = _vector_search(get_db()["sandy_conversations"], query, chat_id, n_results, {})

        if results is None:
            try:
                results = list(
                    coll.find(
                        {"$text": {"$search": query}},
                        {"score": {"$meta": "textScore"}, "text": 1},
                    )
                    .sort([("score", {"$meta": "textScore"})])
                    .limit(n_results)
                )
            except Exception:
                results = list(
                    coll.find({}, {"text": 1}).sort("ts", -1).limit(n_results)
                )

        return [r["text"] for r in results if r.get("text")]
    except Exception as e:
        logger.warning(f"[Memory] search_relevant_conversations: {e}")
        return []


def search_relevant_summaries(query: str, chat_id: str, n_results: int = 3) -> List[str]:
    """Semantic search over conversation summaries in sandy_memories."""
    if get_db() is None or not chat_id:
        return []
    col = get_db()["sandy_memories"]
    fil = {"chat_id": str(chat_id), "label": "conversation_summary"}
    try:
        results = _vector_search(col, query, chat_id, n_results, {})
        if results is None:
            results = list(col.find(fil, {"summary": 1}).sort("created_at", -1).limit(n_results))
        return [r["summary"] for r in results if r.get("summary")]
    except Exception as exc:
        logger.warning(f"[chroma] search_relevant_summaries failed: {exc}")
        return []


def semantic_memory_stats() -> Dict[str, Any]:
    """Return counts for the current user, for health checks and debugging."""
    if not _can_read_memory():
        return {"path": "mongodb", "facts": 0, "conversations": 0}
    facts_count = 0
    convs_count = 0
    facts_coll = _facts_coll()
    if facts_coll is not None:
        try:
            facts_count = facts_coll.count_documents({})
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)
    convs_coll = _convs_coll()
    if convs_coll is not None:
        try:
            convs_count = convs_coll.count_documents({})
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)
    return {
        "path": "mongodb",
        "vector_search": _embed_client is not None,
        "facts": facts_count,
        "conversations": convs_count,
    }


__all__ = [
    "init_mongo_memory",
    "load_facts_to_chroma",
    "load_conversations_to_chroma",
    "search_relevant_facts",
    "search_relevant_conversations",
    "semantic_memory_stats",
]
