"""Chat conversations: many per user, each with a title and messages, plus the turn ledger.

Collection `conversations`: {_id, user_id, title, created_at, updated_at, messages:[{role,text,ts}]}

  GET/POST /api/conversations · GET/PATCH/DELETE /api/conversations/<cid>
  POST /api/conversations/<cid>/messages · GET /api/conversations/search?q=
  POST /api/conversations/<cid>/rewind {keep_user}: drop the last reply (and, unless
       keep_user, the line it answered) here and in Sandy's memory of the thread, and take
       back what that reply did to the blocks, so the app can regenerate a reply or resend
       an edited last message in its place.
  POST /api/conversations/<cid>/stop {partial, client_msg_id}: the reply was stopped.

The app may pick a new chat's id itself; the first write creates it
(`ensure_conversation`), and an id belonging to another user is refused.
`agent_turns` makes chat sends idempotent per `client_msg_id` (claim_turn / finish_turn).
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


# Keeps a thread's single document far from Mongo's 16 MB cap.
_MAX_MESSAGE_CHARS = 20_000

_MAX_SEARCH_RESULTS = 50


# Client-chosen ids: nothing that could smuggle an operator or a path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Processed ids are remembered for _TURN_TTL_S; a "processing" turn older than
# _TURN_STALE_S is presumed abandoned and may be claimed again.
_TURNS = "agent_turns"
_TURN_TTL_S = 600
_TURN_STALE_S = 180

_turn_index_lock = threading.Lock()
# id(db) -> db; holding the handle stops its id being recycled (tests build many).
_turn_index_ready: dict = {}


def valid_client_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def _scoped_for(mongo_db, uid: str, name: str) -> Optional[ScopedCollection]:
    """scoped() for the route's caller; bump=False (threads and turns feed no cached persona)."""
    with active_user_profile_context({"chat_id": uid}):
        return scoped(mongo_db, name, bump=False)


def _conversations(mongo_db, uid: str) -> Optional[ScopedCollection]:
    return _scoped_for(mongo_db, uid, "conversations")


def ensure_conversation(mongo_db, uid: str, cid: str) -> bool:
    """True if `cid` is (or has just become) one of `uid`'s conversations; False if malformed or another user's."""
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
        # A concurrent create of our own, or someone else's id.
        return coll.find_one({"_id": cid}, {"_id": 1}) is not None


def _turns(mongo_db, uid: str) -> ScopedCollection:
    key = id(mongo_db)
    if _turn_index_ready.get(key) is not mongo_db:
        with _turn_index_lock:
            if _turn_index_ready.get(key) is not mongo_db:
                # Indexes on the raw handle (tenant_db's rule).
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

    ("new", None): run it and call finish_turn · ("done", result): already answered ·
    ("processing", None): running elsewhere. A failed or stale turn is re-claimed by
    compare-and-set on `attempt`. No db/user/valid key → no ledger.
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
    if d is None:  # expired between insert and read
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
    """("done", result) / ("processing"|"error"|"missing", None)."""
    if mongo_db is None or not uid or not valid_client_id(cmid):
        return "missing", None
    d = _turns(mongo_db, uid).find_one({"client_msg_id": cmid})
    if d is None:
        return "missing", None
    status = d.get("status") or "processing"
    return status, (dict(d.get("result") or {}) if status == "done" else None)


def finish_turn(mongo_db, uid: str, cmid: str, result: Optional[dict] = None,
                error: bool = False) -> None:
    """Record how a claimed turn ended (best-effort)."""
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
        # A big generated image can exceed Mongo's cap; the text alone still helps a retry.
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


def _attachment_refs(value: Any) -> list:
    """A message's attachments as the history keeps them: [{id, kind, name}], at most four,
    only well-formed ids (the bytes stay in sandy_attachments, read by their owner only)."""
    refs = []
    for a in value if isinstance(value, list) else []:
        if not isinstance(a, dict) or not valid_client_id(a.get("id")):
            continue
        refs.append({"id": a["id"], "kind": "image" if a.get("kind") == "image" else "file",
                     "name": str(a.get("name") or "")[:120]})
    return refs[:4]


def _uid(claims) -> str:
    """Caller's user id, or '' (every query then fails closed)."""
    return str(claims.get("user_id") or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _title_from(text: str) -> str:
    """Fallback title from the first user message, until the LLM title lands."""
    t = " ".join((text or "").split())
    return t[:40] if t else "محادثة جديدة"


def _generate_title(coll, cid: str, uid: str, user_msg: str, reply: str) -> None:
    """Small LLM title from the first exchange; runs in the background."""
    from app.integrations.openai_client import chat_fn

    try:
        resp = chat_fn()(max_tokens=20, messages=[
            {"role": "system", "content": (
                "اكتب عنوانًا قصيرًا جدًا (كلمتين لأربع كلمات) يلخّص موضوع المحادثة. "
                "بنفس لغة المستخدم، بدون علامات اقتباس وبدون نقطة في الآخر."
            )},
            {"role": "user", "content": f"المستخدم: {user_msg}\nساندي: {reply}"},
        ])
        title = (resp.choices[0].message.content or "").strip().strip('"').strip("«»").strip()
        if title:
            coll.update_one({"_id": cid, "user_id": uid},
                            {"$set": {"title": title[:60], "title_generated": True}})
    except Exception:  # noqa: BLE001 — العنوان تحسين، فشله يترك عنوان أول رسالة
        logger.debug("[conversations] title generation failed", exc_info=True)


def _generate_title_async(coll, cid: str, uid: str, user_msg: str, reply: str) -> None:
    from app.utils.thread_pool import submit_background

    submit_background(_generate_title, coll, cid, uid, user_msg, reply,
                      _label="conversation-title")


def _semantic_hits(uid: str, query: str, limit: int = 30):
    """[(conversation_id, summary)] from the caller's own conversation summaries, by meaning.

    Any failure yields [] (text search still answers).
    """
    from app.brain.context import similar_entries

    try:
        with active_user_profile_context({"chat_id": uid}):
            rows = similar_entries(query, k=limit, kind="summary")
    except Exception:  # noqa: BLE001 — text search is the floor
        logger.warning("[conversations] summary search failed", exc_info=True)
        return []
    return [(str((r.get("data") or {}).get("thread_id") or ""), r.get("text", "")) for r in rows]


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
        files = _attachment_refs(body.get("attachments"))
        if role not in ("user", "sandy") or not (text or files):
            return jsonify({"error": "bad_message"}), 400
        # Bounded: every message is pushed onto one document (16 MB cap).
        text = text[:_MAX_MESSAGE_CHARS]

        d = coll.find_one(
            {"_id": cid, "user_id": uid},
            {"title": 1, "title_generated": 1, "messages": {"$slice": -1}},
        )
        if not d:
            # A new chat whose id the app chose; 404 if the id is someone else's.
            if not ensure_conversation(mongo_db, uid, cid):
                return jsonify({"error": "not_found"}), 404
            d = {}

        message = {"role": role, "text": text, "ts": _now()}
        if files:
            message["attachments"] = files
        update = {
            "$push": {"messages": message},
            "$set": {"updated_at": _now()},
        }
        # First user message is the fallback title.
        if role == "user" and not (d.get("title") or "").strip():
            update["$set"]["title"] = _title_from(text)
        coll.update_one({"_id": cid, "user_id": uid}, update)

        # First Sandy reply: generate a smart title from the first exchange.
        if role == "sandy" and not d.get("title_generated"):
            last = (d.get("messages") or [])
            last_user = last[-1].get("text", "") if last and last[-1].get("role") == "user" else ""
            _generate_title_async(coll, cid, uid, last_user, text)
        return jsonify({"ok": True}), 200

    @app.route("/api/conversations/<cid>/rewind", methods=["POST"])
    @require_auth
    def rewind_conversation(claims, cid):
        uid = _uid(claims)
        coll = _coll()
        if not uid or coll is None:
            return jsonify({"error": "no_user"}), 403
        keep_user = bool((request.get_json(silent=True) or {}).get("keep_user"))
        d = coll.find_one({"_id": cid, "user_id": uid}, {"messages": {"$slice": -2}})
        if not d:
            return jsonify({"error": "not_found"}), 404
        tail = [m.get("role") for m in d.get("messages") or []]
        drop = 0
        if tail and tail[-1] == "sandy":
            drop += 1
        if not keep_user and len(tail) > drop and tail[-1 - drop] == "user":
            drop += 1
        for _ in range(drop):
            coll.update_one({"_id": cid, "user_id": uid}, {"$pop": {"messages": 1}})
        from app.blocks import _base as blocks_base
        from app.brain import stm
        # What the dropped reply did (added, changed, deleted) goes back; devices stay as they are.
        effects = stm.rewind(cid, uid)
        with active_user_profile_context({"chat_id": uid}):
            undone = blocks_base.undo(effects, mongo_db)
        return jsonify({"ok": True, "dropped": drop, "undone": undone}), 200

    @app.route("/api/conversations/<cid>/stop", methods=["POST"])
    @require_auth
    def stop_reply(claims, cid):
        """{partial, client_msg_id}: the reply was stopped after `partial`. A turn still
        running stops before its next tool; either way memory keeps only `partial`, cut."""
        uid = _uid(claims)
        if not uid:
            return jsonify({"error": "no_user"}), 403
        body = request.get_json(silent=True) or {}
        partial = str(body.get("partial") or "")[:_MAX_MESSAGE_CHARS]
        from app.brain import stm, stops
        status, _ = turn_status(mongo_db, uid, str(body.get("client_msg_id") or ""))
        if status == "processing":
            stops.request(uid, cid, partial)
        else:
            stm.cut_last(cid, uid, stops.cut(partial))
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
        # 1) Text match over titles + messages, in the database.
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

        # 2) Match over the caller's conversation summaries, limited to their own threads.
        if len(items) >= _MAX_SEARCH_RESULTS:
            return jsonify({"items": items}), 200
        hits = [(cid, s) for cid, s in _semantic_hits(uid, q) if cid and cid not in seen]
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
