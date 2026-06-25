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
    """A short title from the first user message (Phase B upgrades to an LLM call)."""
    t = " ".join((text or "").split())
    return t[:40] if t else "محادثة جديدة"


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

        d = coll.find_one({"_id": cid, "user_id": uid}, {"title": 1})
        if not d:
            return jsonify({"error": "not_found"}), 404

        update = {
            "$push": {"messages": {"role": role, "text": text, "ts": _now()}},
            "$set": {"updated_at": _now()},
        }
        # First user message becomes the title until renamed.
        if role == "user" and not (d.get("title") or "").strip():
            update["$set"]["title"] = _title_from(text)
        coll.update_one({"_id": cid, "user_id": uid}, update)
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
            if len(items) >= 50:
                break
        return jsonify({"items": items}), 200
