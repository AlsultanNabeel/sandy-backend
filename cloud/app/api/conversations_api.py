"""Chat conversations API — multi-conversation history per user.

The chat used to be one flat blob (`web_chat_history`, GET/PUT replace). This is
the real model: many conversations per user, each with its own title + messages,
auto-saved, browsable, searchable. Phase A (foundation): CRUD + text search +
auto title from the first user message. Phase B will add rolling summaries,
topic segmentation and semantic search on top of the same documents.

Every read/write is scoped to the caller's user_id and fails closed when there's
no user (guests get an empty list, never another user's chats).

Collection `conversations`:
  {_id: uuid-hex, user_id, title, created_at, updated_at, messages:[{role,text,ts}]}

Endpoints:
  GET    /api/conversations                  list (id/title/timestamps), newest first
  POST   /api/conversations                  create → {id}
  GET    /api/conversations/<cid>            one conversation with messages
  PATCH  /api/conversations/<cid>            rename {title}
  DELETE /api/conversations/<cid>            delete
  POST   /api/conversations/<cid>/messages   append {role,text}; sets title if empty
  GET    /api/conversations/search?q=        text search over titles + messages

A conversation can also be created implicitly: the app picks the id itself
(a uuid hex) for a new chat and the first write that names it — the chat
stream route or the message append — creates it for the caller
(`ensure_conversation`). That removes a round trip before the first token.
An id that already belongs to another user is refused, never written into.

Turn ledger (`agent_turns`): the chat routes take an optional idempotency key
`client_msg_id` per user message so the app can retry a send cut off by the
network without running the turn twice (`claim_turn` / `finish_turn`).
"""

from __future__ import annotations
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from flask import jsonify, request
from pymongo.errors import DuplicateKeyError

from app.api.auth_handlers import require_auth
from app.utils.tenant_db import ScopedCollection, scoped
from app.utils.user_profiles import active_user_profile_context
from app.utils.text_query import contains

logger = logging.getLogger(__name__)


# Longer than any real chat message; short enough that a thread's document stays
# far from Mongo's 16 MB cap.
_MAX_MESSAGE_CHARS = 20_000

# Most results one search returns (text and semantic matches together).
_MAX_SEARCH_RESULTS = 50


# A client-chosen conversation id / message key: uuid hex (or dashed uuid),
# nothing that could smuggle an operator or a path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Turn ledger: how long a processed `client_msg_id` is remembered (Mongo TTL),
# and after how long a turn still marked "processing" is presumed abandoned
# (worker died with the process) and may be claimed again.
_TURNS = "agent_turns"
_TURN_TTL_S = 600
_TURN_STALE_S = 180

_turn_index_lock = threading.Lock()
# id(db) -> db. The handle is held so its id can't be recycled by a new
# database object (tests build many) that would then skip index creation.
_turn_index_ready: dict = {}


def valid_client_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def _scoped_for(mongo_db, uid: str, name: str) -> Optional[ScopedCollection]:
    """`tenant_db.scoped` for `uid` (the route's caller) — every filter gets
    user_id=uid, every insert is stamped with it. bump=False: a chat thread
    and a turn record feed nothing the cached persona block is built from."""
    with active_user_profile_context({"chat_id": uid}):
        return scoped(mongo_db, name, bump=False)


def _conversations(mongo_db, uid: str) -> Optional[ScopedCollection]:
    return _scoped_for(mongo_db, uid, "conversations")


def ensure_conversation(mongo_db, uid: str, cid: str) -> bool:
    """Make sure `cid` is one of `uid`'s conversations, creating it (empty,
    untitled — the first user message titles it, as with POST) when no such id
    exists. False when the id is malformed or belongs to someone else: `_id` is
    unique across users, so the insert fails and the scoped re-read finds
    nothing — another user's thread is never read or written.
    """
    if mongo_db is None or not uid or not valid_client_id(cid):
        return False
    coll = _conversations(mongo_db, uid)
    if coll is None:
        return False
    if coll.find_one({"_id": cid}, {"_id": 1}) is not None:
        return True
    now = _now()
    try:
        coll.insert_one({
            "_id": cid,
            "title": "",
            "title_generated": False,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        })
        return True
    except DuplicateKeyError:
        # Either a concurrent create of our own (the stream and the append
        # race on a new chat's first message) or someone else's id.
        return coll.find_one({"_id": cid}, {"_id": 1}) is not None


def _turns(mongo_db, uid: str) -> ScopedCollection:
    key = id(mongo_db)
    if _turn_index_ready.get(key) is not mongo_db:
        with _turn_index_lock:
            if _turn_index_ready.get(key) is not mongo_db:
                # Index management stays on the raw handle (tenant_db's rule);
                # both indexes lead with / are independent of the tenant.
                raw = mongo_db[_TURNS]
                try:
                    raw.create_index([("user_id", 1), ("client_msg_id", 1)],
                                     unique=True, name="user_client_msg_unique")
                    raw.create_index("created_at", expireAfterSeconds=_TURN_TTL_S,
                                     name="created_at_ttl")
                    _turn_index_ready[key] = mongo_db
                except Exception:  # noqa: BLE001 — retried on the next call
                    logger.warning("[turns] index creation failed", exc_info=True)
    return _scoped_for(mongo_db, uid, _TURNS)


def _age_s(ts) -> float:
    if not isinstance(ts, datetime):
        return 0.0
    if ts.tzinfo is None:  # Mongo hands datetimes back naive (UTC)
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def claim_turn(mongo_db, uid: str, cmid: str) -> Tuple[str, Optional[dict]]:
    """Claim the turn for (uid, client_msg_id).

    Returns ("new", None) — the caller runs the turn and must `finish_turn`;
    ("done", result) — already answered, return the stored reply;
    ("processing", None) — another request is running it right now.
    A turn whose earlier run failed, or that has sat in "processing" past
    `_TURN_STALE_S`, is claimed again (compare-and-set on `attempt`, so only
    one retry wins). Without a db, a user or a valid key there is no ledger.
    """
    if mongo_db is None or not uid or not valid_client_id(cmid):
        return "new", None
    coll = _turns(mongo_db, uid)
    now = datetime.now(timezone.utc)
    try:
        coll.insert_one({"client_msg_id": cmid, "status": "processing",
                         "attempt": 1, "created_at": now})
        return "new", None
    except DuplicateKeyError:
        pass
    d = coll.find_one({"client_msg_id": cmid})
    if d is None:  # expired between the insert and the read — take it fresh
        try:
            coll.insert_one({"client_msg_id": cmid, "status": "processing",
                             "attempt": 1, "created_at": now})
            return "new", None
        except DuplicateKeyError:
            return "processing", None
    status = d.get("status")
    if status == "done":
        return "done", dict(d.get("result") or {})
    if status == "error" or (status == "processing"
                             and _age_s(d.get("claimed_at") or d.get("created_at")) > _TURN_STALE_S):
        attempt = int(d.get("attempt") or 1)
        won = coll.find_one_and_update(
            {"client_msg_id": cmid, "attempt": attempt},
            {"$set": {"status": "processing", "attempt": attempt + 1, "claimed_at": now}},
        )
        return ("new", None) if won is not None else ("processing", None)
    return "processing", None


def turn_status(mongo_db, uid: str, cmid: str) -> Tuple[str, Optional[dict]]:
    """Current ledger state: ("done", result) / ("processing", None) /
    ("error", None) / ("missing", None)."""
    if mongo_db is None or not uid or not valid_client_id(cmid):
        return "missing", None
    d = _turns(mongo_db, uid).find_one({"client_msg_id": cmid})
    if d is None:
        return "missing", None
    status = d.get("status") or "processing"
    return status, (dict(d.get("result") or {}) if status == "done" else None)


def finish_turn(mongo_db, uid: str, cmid: str, result: Optional[dict] = None,
                error: bool = False) -> None:
    """Record how a claimed turn ended. Best-effort: a failed write only
    costs a retry its shortcut (it re-runs after the stale window)."""
    if mongo_db is None or not uid or not valid_client_id(cmid):
        return
    coll = _turns(mongo_db, uid)
    fields = {"status": "error"} if error else {"status": "done", "result": result or {}}
    try:
        coll.update_one({"client_msg_id": cmid}, {"$set": fields})
    except Exception:  # noqa: BLE001
        if error or "image_url" not in (result or {}):
            logger.warning("[turns] finish failed", exc_info=True)
            return
        # A big generated image can push the record past Mongo's cap; the
        # text alone still spares the retry a second run.
        try:
            slim = {k: v for k, v in (result or {}).items() if k != "image_url"}
            coll.update_one({"client_msg_id": cmid},
                            {"$set": {"status": "done", "result": slim}})
        except Exception:  # noqa: BLE001
            logger.warning("[turns] finish failed", exc_info=True)


def release_turn(mongo_db, uid: str, cmid: str) -> None:
    """Forget a claim that never ran (e.g. refused by the quota)."""
    if mongo_db is None or not uid or not valid_client_id(cmid):
        return
    try:
        _turns(mongo_db, uid).delete_one({"client_msg_id": cmid, "status": "processing"})
    except Exception:  # noqa: BLE001
        logger.warning("[turns] release failed", exc_info=True)


def _uid(claims) -> str:
    """Caller's user id, or '' which every query treats as fail-closed."""
    return str(claims.get("user_id") or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _title_from(text: str) -> str:
    """A short fallback title from the first user message (used until the LLM
    title lands, and if the LLM is unavailable)."""
    t = " ".join((text or "").split())
    return t[:40] if t else "محادثة جديدة"


def _generate_title(coll, cid: str, uid: str, user_msg: str, reply: str) -> None:
    """Generate a short smart title from the first exchange and store it. Runs in
    a background thread (a small LLM call) so it never slows the message append."""
    try:
        from app.config import (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,
                                 AZURE_OPENAI_API_VERSION, AZURE_OPENAI_CHAT_DEPLOYMENT)
        from openai import AzureOpenAI

        if not AZURE_OPENAI_API_KEY:
            return
        client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
            max_retries=0,  # fail fast — the SDK's default retries silently triple any timeout
        )
        from app.integrations.azure_intent_client import _create_chat_resilient
        from app.integrations.openai_client import DEFAULT_CHAT_TIMEOUT_S

        # Adapter, breaker and a deadline — this runs on the shared background
        # pool, where a hung call would hold a worker indefinitely.
        resp = _create_chat_resilient(client, {
            "model": AZURE_OPENAI_CHAT_DEPLOYMENT,
            "messages": [
                {"role": "system", "content": (
                    "اكتب عنوانًا قصيرًا جدًا (كلمتين لأربع كلمات) يلخّص موضوع المحادثة. "
                    "بنفس لغة المستخدم، بدون علامات اقتباس وبدون نقطة في الآخر."
                )},
                {"role": "user", "content": f"المستخدم: {user_msg}\nساندي: {reply}"},
            ],
            "max_tokens": 20,
            "timeout": DEFAULT_CHAT_TIMEOUT_S,
        })
        title = (resp.choices[0].message.content or "").strip().strip('"').strip("«»").strip()
        if title:
            coll.update_one({"_id": cid, "user_id": uid},
                            {"$set": {"title": title[:60], "title_generated": True}})
    except Exception:  # noqa: BLE001 — العنوان تحسين، فشله يترك عنوان أول رسالة
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)


def _generate_title_async(coll, cid: str, uid: str, user_msg: str, reply: str) -> None:
    from app.utils.thread_pool import submit_background

    submit_background(_generate_title, coll, cid, uid, user_msg, reply,
                      _label="conversation-title")


def _semantic_hits(mongo_db, query: str, limit: int = 30):
    """Conversation ids whose rolling summary is semantically close to the query —
    reuses the agent's vector-indexed LTM (`sandy_memories`, label
    `conversation_summary`, keyed by chat_id == conversation_id). Returns
    [(conversation_id, summary)]; ownership is enforced by the caller's lookup in
    `conversations`. Best-effort: any failure (no embeddings / no vector index)
    yields [] and the text search alone still answers.
    """
    if mongo_db is None:
        return []
    try:
        from app.agent.semantic_memory import _embed
        vec = _embed(query)
        if not vec:
            return []
        pipeline = [
            {"$vectorSearch": {
                "index": "sandy_vector_index",
                "path": "embedding",
                "queryVector": vec,
                "numCandidates": 80,
                "limit": limit,
                "filter": {"label": {"$eq": "conversation_summary"}},
            }},
            {"$project": {"chat_id": 1, "summary": 1}},
        ]
        return [
            (str(d.get("chat_id", "")), d.get("summary", ""))
            for d in mongo_db["sandy_memories"].aggregate(pipeline)
        ]
    except Exception:  # noqa: BLE001 — semantic is additive; text search is the floor
        return []


def register_conversations_api(app, mongo_db=None):
    def _coll():
        return None if mongo_db is None else mongo_db["conversations"]

    @app.route("/api/conversations", methods=["GET"])
    @require_auth
    def list_conversations(claims):
        uid = _uid(claims)
        coll = _coll()
        if not uid or coll is None:
            return jsonify({"items": []}), 200
        items = []
        for d in coll.find(
            {"user_id": uid},
            {"title": 1, "created_at": 1, "updated_at": 1},
        ).sort("updated_at", -1).limit(200):
            items.append({
                "id": str(d["_id"]),
                "title": d.get("title", "") or "محادثة",
                "created_at": d.get("created_at", ""),
                "updated_at": d.get("updated_at", ""),
            })
        return jsonify({"items": items}), 200

    @app.route("/api/conversations", methods=["POST"])
    @require_auth
    def create_conversation(claims):
        uid = _uid(claims)
        coll = _coll()
        if not uid or coll is None:
            return jsonify({"error": "no_user"}), 403
        body = request.get_json(silent=True) or {}
        cid = uuid.uuid4().hex
        now = _now()
        coll.insert_one({
            "_id": cid,
            "user_id": uid,
            "title": (body.get("title") or "").strip(),
            "title_generated": False,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        })
        return jsonify({"id": cid}), 200

    @app.route("/api/conversations/<cid>", methods=["GET"])
    @require_auth
    def get_conversation(claims, cid):
        uid = _uid(claims)
        coll = _coll()
        if not uid or coll is None:
            return jsonify({"error": "not_found"}), 404
        d = coll.find_one({"_id": cid, "user_id": uid})
        if not d:
            return jsonify({"error": "not_found"}), 404
        return jsonify({
            "id": str(d["_id"]),
            "title": d.get("title", ""),
            "created_at": d.get("created_at", ""),
            "updated_at": d.get("updated_at", ""),
            "messages": d.get("messages", []),
        }), 200

    @app.route("/api/conversations/<cid>", methods=["PATCH"])
    @require_auth
    def rename_conversation(claims, cid):
        uid = _uid(claims)
        coll = _coll()
        if not uid or coll is None:
            return jsonify({"error": "no_user"}), 403
        title = (request.get_json(silent=True) or {}).get("title", "").strip()
        coll.update_one({"_id": cid, "user_id": uid},
                        {"$set": {"title": title, "updated_at": _now()}})
        return jsonify({"ok": True}), 200

    @app.route("/api/conversations/<cid>", methods=["DELETE"])
    @require_auth
    def delete_conversation(claims, cid):
        uid = _uid(claims)
        coll = _coll()
        if not uid or coll is None:
            return jsonify({"error": "no_user"}), 403
        coll.delete_one({"_id": cid, "user_id": uid})
        return jsonify({"ok": True}), 200

    @app.route("/api/conversations/<cid>/messages", methods=["POST"])
    @require_auth
    def append_message(claims, cid):
        uid = _uid(claims)
        coll = _coll()
        if not uid or coll is None:
            return jsonify({"error": "no_user"}), 403
        body = request.get_json(silent=True) or {}
        role = (body.get("role") or "").strip()
        text = (body.get("text") or "").strip()
        if role not in ("user", "sandy") or not text:
            return jsonify({"error": "bad_message"}), 400
        # One message, bounded. Every message is pushed onto a single document,
        # and Mongo caps a document at 16 MB — one oversized append was enough
        # to make every later write to the thread fail.
        text = text[:_MAX_MESSAGE_CHARS]

        d = coll.find_one(
            {"_id": cid, "user_id": uid},
            {"title": 1, "title_generated": 1, "messages": {"$slice": -1}},
        )
        if not d:
            # A new chat whose id the app chose: the append may land before
            # the chat stream created it. Create it for this user — or 404
            # when the id is someone else's.
            if not ensure_conversation(mongo_db, uid, cid):
                return jsonify({"error": "not_found"}), 404
            d = {}

        update = {
            "$push": {"messages": {"role": role, "text": text, "ts": _now()}},
            "$set": {"updated_at": _now()},
        }
        # First user message becomes the fallback title until the smart one lands.
        if role == "user" and not (d.get("title") or "").strip():
            update["$set"]["title"] = _title_from(text)
        coll.update_one({"_id": cid, "user_id": uid}, update)

        # On the first Sandy reply, generate a smart title from the first exchange.
        if role == "sandy" and not d.get("title_generated"):
            last = (d.get("messages") or [])
            last_user = last[-1].get("text", "") if last and last[-1].get("role") == "user" else ""
            _generate_title_async(coll, cid, uid, last_user, text)
        return jsonify({"ok": True}), 200

    @app.route("/api/conversations/search", methods=["GET"])
    @require_auth
    def search_conversations(claims):
        uid = _uid(claims)
        coll = _coll()
        q = (request.args.get("q") or "").strip()
        if not uid or coll is None or not q:
            return jsonify({"items": []}), 200
        items = []
        seen = set()
        # 1) Text match over titles + messages, done by the database. This used
        #    to pull the 300 newest threads whole — every message of every one —
        #    to scan them here; now only matching threads come back, each with
        #    its title and the first matching message.
        in_title = contains("title", q)
        in_message = contains("text", q)
        title_hit = re.compile(in_title["title"]["$regex"], re.IGNORECASE)
        for d in coll.find(
            {"user_id": uid, "$or": [in_title, {"messages": {"$elemMatch": in_message}}]},
            {"title": 1, "updated_at": 1, "messages": {"$elemMatch": in_message}},
        ).sort("updated_at", -1).limit(_MAX_SEARCH_RESULTS):
            title = d.get("title", "") or ""
            matched = d.get("messages") or []
            if title_hit.search(title) or not matched:
                snippet = title
            else:
                snippet = matched[0].get("text", "") or ""
            items.append({
                "id": str(d["_id"]),
                "title": title or "محادثة",
                "snippet": snippet[:120],
                "updated_at": d.get("updated_at", ""),
            })
            seen.add(str(d["_id"]))

        # 2) Semantic match over rolling summaries (finds it by meaning, not words).
        #    Ownership enforced here: we only surface the caller's own conversations,
        #    looked up in one query rather than one per hit.
        if len(items) >= _MAX_SEARCH_RESULTS:
            return jsonify({"items": items}), 200
        hits = [(cid, s) for cid, s in _semantic_hits(mongo_db, q) if cid and cid not in seen]
        owned = {
            str(c["_id"]): c
            for c in coll.find(
                {"_id": {"$in": [cid for cid, _ in hits]}, "user_id": uid},
                {"title": 1, "updated_at": 1},
            ).limit(len(hits))
        } if hits else {}
        for cid, summary in hits:
            c = owned.get(cid)
            if c is None or cid in seen or len(items) >= _MAX_SEARCH_RESULTS:
                continue
            items.append({
                "id": cid,
                "title": c.get("title", "") or "محادثة",
                "snippet": (summary or "")[:120],
                "updated_at": c.get("updated_at", ""),
            })
            seen.add(cid)
        return jsonify({"items": items}), 200
