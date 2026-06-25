"""Memory API — what Sandy remembers about you (the user-facing memory view).

Reads the SAME store the agent's `memory_store` tool writes to: the user's saved
facts in `sandy_memories` (chat_id == user_id, field `content`). It EXCLUDES the
automatic rolling conversation summaries (label `conversation_summary`) — those are
internal plumbing, not user-facing facts. Real data only; no demo payloads.

Scoped to the caller's own user_id (isolated); guests get nothing.

User facts are stored plainly (no embedding — only the rolling
`conversation_summary` docs are vector-indexed), so add/edit are a simple
insert/update mirroring the `memory_store` tool's shape.

Endpoints:
  GET    /api/memory            this user's saved facts
  POST   /api/memory            remember a new fact
  PATCH  /api/memory/<fact_id>  edit one fact's text
  DELETE /api/memory/<fact_id>  forget one fact
"""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)


def register_memory_api(app, mongo_db=None):
    @app.route("/api/memory", methods=["GET"])
    @require_auth
    def get_memory(claims):
        if mongo_db is None:
            return jsonify({"items": []}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"items": []}), 200
            items = []
            cur = (
                mongo_db["sandy_memories"]
                .find(
                    {"chat_id": uid, "label": {"$ne": "conversation_summary"}},
                    {"content": 1, "label": 1},
                )
                .sort("created_at", -1)
                .limit(300)
            )
            for d in cur:
                text = (d.get("content") or "").strip()
                if not text:
                    continue
                items.append({
                    "id": str(d["_id"]),
                    "text": text,
                    "type": d.get("label", "user_fact"),
                })
        return jsonify({"items": items}), 200

    @app.route("/api/memory", methods=["POST"])
    @require_auth
    def add_memory(claims):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
        if not text:
            return jsonify({"error": "text_required"}), 400
        from datetime import datetime, timezone

        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            # Same shape the memory_store tool writes (plain user_fact, no embedding).
            res = mongo_db["sandy_memories"].insert_one({
                "chat_id": uid,
                "label": "user_fact",
                "content": text,
                "created_at": datetime.now(timezone.utc),
            })
        return jsonify({"ok": True, "id": str(res.inserted_id)}), 200

    @app.route("/api/memory/<fact_id>", methods=["PATCH"])
    @require_auth
    def update_memory(claims, fact_id):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
        if not text:
            return jsonify({"error": "text_required"}), 400
        try:
            oid = ObjectId(fact_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            # Scoped + never edits an auto summary by id.
            res = mongo_db["sandy_memories"].update_one(
                {"_id": oid, "chat_id": uid, "label": {"$ne": "conversation_summary"}},
                {"$set": {"content": text}},
            )
        return jsonify({"ok": res.matched_count > 0}), (200 if res.matched_count else 400)

    @app.route("/api/memory/<fact_id>", methods=["DELETE"])
    @require_auth
    def delete_memory(claims, fact_id):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(fact_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            # Scoped + never deletes an auto summary by id.
            res = mongo_db["sandy_memories"].delete_one(
                {"_id": oid, "chat_id": uid, "label": {"$ne": "conversation_summary"}}
            )
        return jsonify({"ok": res.deleted_count > 0}), 200
