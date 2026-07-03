"""Device push-token registration (Phase 7).

The app calls these after the user grants notification permission, so the daily
scheduler knows where to deliver. Guests can't register (nothing to notify).

  POST /api/push/register    {token, platform?}  bind this device to the user
  POST /api/push/unregister  {token}             drop it (logout / opt-out)
"""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.features import push_tokens_store


def register_push_api(app):
    @app.route("/api/push/register", methods=["POST"])
    @require_auth
    def api_push_register(claims):
        if claims.get("role") == "guest":
            return jsonify({"error": "forbidden"}), 403
        uid = claims.get("user_id") or ""
        body = request.get_json(silent=True) or {}
        token = str(body.get("token") or "").strip()
        platform = str(body.get("platform") or "ios").strip()
        if not uid or not token:
            return jsonify({"error": "bad_request"}), 400
        ok = push_tokens_store.register_token(uid, token, platform)
        return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "save_failed"}), 400)

    @app.route("/api/push/unregister", methods=["POST"])
    @require_auth
    def api_push_unregister(claims):
        body = request.get_json(silent=True) or {}
        token = str(body.get("token") or "").strip()
        if not token:
            return jsonify({"error": "bad_request"}), 400
        push_tokens_store.unregister_token(token)
        return jsonify({"ok": True}), 200
