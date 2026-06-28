"""Goals API — the user-facing view of the goals Sandy tracks for you.

Reads the SAME store the agent's goal tools write to: ``sandy_goals`` (see
``app/agent/tools/schemas/goal_tools.py``). Each goal doc is keyed by ``chat_id``
(the user's own id) and carries ``text``, an optional ``deadline``, a ``status``
of ``active``/``done``, plus ``created_at`` / ``updated_at`` timestamps. No new
schema is invented here — add/edit/done mirror exactly what the tools persist.

Scoped to the caller's own user_id (isolated); guests get nothing and every
mutating route is fail-closed, just like memory_api / life_api.

Endpoints:
  GET    /api/goals             this user's goals (active + done)
  POST   /api/goals             set a new goal
  PATCH  /api/goals/<goal_id>   edit text / deadline / status (mark done or reopen)
  DELETE /api/goals/<goal_id>   drop a goal
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)

_COLL = "sandy_goals"


def register_goals_api(app, mongo_db=None):
    @app.route("/api/goals", methods=["GET"])
    @require_auth
    def get_goals(claims):
        if mongo_db is None:
            return jsonify({"items": []}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"items": []}), 200
            items = []
            cur = (
                mongo_db[_COLL]
                .find(
                    {"chat_id": uid},
                    {"text": 1, "deadline": 1, "status": 1},
                )
                .sort("created_at", 1)
                .limit(300)
            )
            for d in cur:
                text = (d.get("text") or "").strip()
                if not text:
                    continue
                items.append({
                    "id": str(d["_id"]),
                    "text": text,
                    "deadline": d.get("deadline") or "",
                    "status": d.get("status") or "active",
                })
        return jsonify({"items": items}), 200

    @app.route("/api/goals", methods=["POST"])
    @require_auth
    def add_goal(claims):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text_required"}), 400
        deadline = (body.get("deadline") or "").strip() or None
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            now = datetime.now(timezone.utc)
            # Same doc shape the goal_set tool writes.
            res = mongo_db[_COLL].insert_one({
                "chat_id": uid,
                "user_id": uid,
                "text": text,
                "deadline": deadline,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            })
        return jsonify({"ok": True, "id": str(res.inserted_id)}), 200

    @app.route("/api/goals/<goal_id>", methods=["PATCH"])
    @require_auth
    def update_goal(claims, goal_id):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        body = request.get_json(silent=True) or {}
        # Only set fields that were sent; absent field = leave unchanged.
        changes = {}
        if "text" in body:
            text = (body.get("text") or "").strip()
            if not text:
                return jsonify({"error": "text_required"}), 400
            changes["text"] = text
        if "deadline" in body:
            changes["deadline"] = (body.get("deadline") or "").strip() or None
        if "status" in body:
            status = (body.get("status") or "").strip()
            if status not in ("active", "done"):
                return jsonify({"error": "bad_status"}), 400
            changes["status"] = status
        if not changes:
            return jsonify({"ok": False, "error": "nothing_to_update"}), 400
        try:
            oid = ObjectId(goal_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        changes["updated_at"] = datetime.now(timezone.utc)
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            res = mongo_db[_COLL].update_one(
                {"_id": oid, "chat_id": uid},
                {"$set": changes},
            )
        return jsonify({"ok": res.matched_count > 0}), (200 if res.matched_count else 400)

    @app.route("/api/goals/<goal_id>", methods=["DELETE"])
    @require_auth
    def delete_goal(claims, goal_id):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(goal_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            res = mongo_db[_COLL].delete_one({"_id": oid, "chat_id": uid})
        return jsonify({"ok": res.deleted_count > 0}), 200
