"""Push-token registration: POST /api/push/register {token, platform?}, /api/push/unregister {token}."""

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
        push_tokens_store.unregister_token(token, user_id=str(claims.get("user_id") or ""))
        return jsonify({"ok": True}), 200
