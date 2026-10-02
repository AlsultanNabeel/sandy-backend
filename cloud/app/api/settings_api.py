"""Profile › Notifications and Profile › Support.

  GET/POST /api/notification-settings  {reminders, daily, proactive, quiet_start, quiet_end}
  POST     /api/feedback               {text, version, device, os}: a note to the team

Feedback lands in `sandy_feedback` with who sent it and from which app and device.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.db import get_db
from app.features import notify_prefs

_MAX_FEEDBACK_CHARS = 4000
_MAX_META_CHARS = 80


def register_settings_api(app):
    @app.route("/api/notification-settings", methods=["GET"])
    @require_auth
    def api_notification_settings(claims):
        return jsonify(notify_prefs.get(claims.get("user_id") or "")), 200

    @app.route("/api/notification-settings", methods=["POST"])
    @require_auth
    def api_notification_settings_save(claims):
        try:
            changes = notify_prefs.clean(request.get_json(silent=True) or {})
        except ValueError:
            return jsonify({"error": "invalid_time", "message": "الوقت لازم يكون بصيغة ساعة ودقيقة."}), 400
        return jsonify(notify_prefs.save(claims.get("user_id") or "", changes)), 200

    @app.route("/api/feedback", methods=["POST"])
    @require_auth
    def api_feedback(claims):
        body = request.get_json(silent=True) or {}
        text = str(body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "empty", "message": "اكتب ملاحظتك أول."}), 400
        db = get_db()
        if db is None:
            return jsonify({"error": "not_saved", "message": "ما وصلت، جرّب كمان شوي."}), 503
        db["sandy_feedback"].insert_one({
            "user_id": claims.get("user_id") or "",
            "text": text[:_MAX_FEEDBACK_CHARS],
            "version": str(body.get("version") or "")[:_MAX_META_CHARS],
            "device": str(body.get("device") or "")[:_MAX_META_CHARS],
            "os": str(body.get("os") or "")[:_MAX_META_CHARS],
            "created_at": datetime.now(timezone.utc),
        })
        return jsonify({"ok": True}), 200
