"""Memory API — what Sandy remembers about you (the user-facing memory view).

Reads the SAME store the agent's `memory_store` tool writes to: the user's saved
facts in `sandy_memories` (chat_id == user_id, field `content`). It EXCLUDES the
automatic rolling conversation summaries (label `conversation_summary`) — those are
internal plumbing, not user-facing facts. Real data only; no demo payloads.

Scoped to the caller's own user_id (isolated); guests get nothing.

Endpoints:
  GET    /api/memory            this user's saved facts
  DELETE /api/memory/<fact_id>  forget one fact
"""

from __future__ import annotations

from flask import jsonify

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
