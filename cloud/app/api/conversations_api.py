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
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from app.api.auth_handlers import require_auth


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
        )
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": (
                    "اكتب عنوانًا قصيرًا جدًا (كلمتين لأربع كلمات) يلخّص موضوع المحادثة. "
                    "بنفس لغة المستخدم، بدون علامات اقتباس وبدون نقطة في الآخر."
                )},
                {"role": "user", "content": f"المستخدم: {user_msg}\nساندي: {reply}"},
            ],
            max_tokens=20,
        )
        title = (resp.choices[0].message.content or "").strip().strip('"').strip("«»").strip()
        if title:
            coll.update_one({"_id": cid, "user_id": uid},
                            {"$set": {"title": title[:60], "title_generated": True}})
    except Exception:  # noqa: BLE001 — العنوان تحسين، فشله يترك عنوان أول رسالة
        pass


def _generate_title_async(coll, cid: str, uid: str, user_msg: str, reply: str) -> None:
    import threading
    threading.Thread(
        target=_generate_title, args=(coll, cid, uid, user_msg, reply), daemon=True
    ).start()


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

        d = coll.find_one(
            {"_id": cid, "user_id": uid},
            {"title": 1, "title_generated": 1, "messages": {"$slice": -1}},
        )
        if not d:
            return jsonify({"error": "not_found"}), 404

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
        ql = q.lower()
        items = []
        seen = set()
        # 1) Text match over titles + messages (covers every conversation).
        for d in coll.find({"user_id": uid}).sort("updated_at", -1).limit(300):
            title = d.get("title", "") or ""
            snippet = ""
            if ql in title.lower():
                snippet = title
            else:
                for m in d.get("messages", []):
                    if ql in (m.get("text", "") or "").lower():
                        snippet = m["text"]
                        break
                else:
                    continue
            items.append({
                "id": str(d["_id"]),
                "title": title or "محادثة",
                "snippet": snippet[:120],
                "updated_at": d.get("updated_at", ""),
            })
            seen.add(str(d["_id"]))
            if len(items) >= 50:
                break

        # 2) Semantic match over rolling summaries (finds it by meaning, not words).
        #    Ownership enforced here: we only surface the caller's own conversations.
        for cid, summary in _semantic_hits(mongo_db, q):
            if not cid or cid in seen or len(items) >= 50:
                continue
            c = coll.find_one({"_id": cid, "user_id": uid}, {"title": 1, "updated_at": 1})
            if not c:
                continue
            items.append({
                "id": cid,
                "title": c.get("title", "") or "محادثة",
                "snippet": (summary or "")[:120],
                "updated_at": c.get("updated_at", ""),
            })
            seen.add(cid)
        return jsonify({"items": items}), 200
