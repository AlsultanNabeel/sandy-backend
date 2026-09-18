"""Future Messages API — schedule a message to your future self.

User-facing view over the SAME store the agent's ``schedule_message_to_self`` tool
writes to (``app.agent.future_messages``). Every read and write goes through that
module's tenant-scoped handle, so the stored shape never diverges and a caller
only ever sees their own messages. ``text`` is encrypted at rest, and delivery is
passive — Sandy surfaces a message in her next reply once ``deliver_at`` passes.

Guests (no tenant) get nothing.

Endpoints:
  GET    /api/future-messages            this user's upcoming scheduled messages
  POST   /api/future-messages            schedule a new message (text + deliver_at)
  DELETE /api/future-messages/<msg_id>   cancel one scheduled message
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify, request

from app.agent.future_messages import (
    cancel_message,
    list_pending_messages,
    schedule_future_message,
)
from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)


def _parse_deliver_at(raw: str) -> datetime | None:
    """Parse an ISO datetime from the client into an aware UTC datetime.

    The app sends ISO 8601 (e.g. ``2027-05-16T09:00:00`` or with a ``Z``). A naive
    value is treated as UTC so it matches how ``schedule_future_message`` stores it.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def register_future_messages_api(app, mongo_db=None):
    @app.route("/api/future-messages", methods=["GET"])
    @require_auth
    def get_future_messages(claims):
        if mongo_db is None:
            return jsonify({"items": []}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"items": []}), 200
            from app.agent.ltm_crypto import decrypt_field

            items = []
            for d in list_pending_messages():
                text = decrypt_field(d.get("text", "")).strip()
                if not text:
                    continue
                deliver_at = d.get("deliver_at")
                created_at = d.get("created_at")
                items.append({
                    "id": str(d["_id"]),
                    "text": text,
                    "deliver_at": deliver_at.isoformat() if isinstance(deliver_at, datetime) else "",
                    "created_at": created_at.isoformat() if isinstance(created_at, datetime) else "",
                })
        return jsonify({"items": items}), 200

    @app.route("/api/future-messages", methods=["POST"])
    @require_auth
    def add_future_message(claims):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text_required"}), 400
        deliver_at = _parse_deliver_at(body.get("deliver_at") or "")
        if deliver_at is None:
            return jsonify({"error": "deliver_at_required"}), 400
        if deliver_at <= datetime.now(timezone.utc):
            return jsonify({"error": "deliver_at_in_past"}), 400

        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            ok = schedule_future_message(text, deliver_at)
        return jsonify({"ok": ok}), (200 if ok else 400)

    @app.route("/api/future-messages/<msg_id>", methods=["DELETE"])
    @require_auth
    def delete_future_message(claims, msg_id):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(msg_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            ok = cancel_message(oid)
        return jsonify({"ok": ok}), 200
