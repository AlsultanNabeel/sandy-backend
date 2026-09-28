"""GET/POST /api/onboarding: first-open preferred name, interests and notes (sandy_users.onboarding)."""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.features import users_store

_MAX_INTERESTS = 20
# Bounded: these go into every prompt.
_MAX_NAME = 60
_MAX_INTEREST = 60
_MAX_NOTES = 2000


def register_onboarding_api(app):
    @app.route("/api/onboarding", methods=["GET"])
    @require_auth
    def api_get_onboarding(claims):
        user = users_store.get_user(claims.get("user_id") or "") or {}
        onboarding = user.get("onboarding") or {}
        interests = onboarding.get("interests") or []
        if not isinstance(interests, list):
            interests = []
        return jsonify({
            "done": bool(onboarding.get("done", False)),
            "preferred_name": str(onboarding.get("preferred_name", "") or ""),
            "interests": [str(i) for i in interests],
            "name": str(user.get("name", "") or ""),
        }), 200

    @app.route("/api/onboarding", methods=["POST"])
    @require_auth
    def api_save_onboarding(claims):
        user_id = claims.get("user_id") or ""
        if not user_id:
            return jsonify({"error": "no_user"}), 400

        body = request.get_json(silent=True) or {}

        preferred_name = str(body.get("preferred_name") or "").strip()[:_MAX_NAME]

        raw_interests = body.get("interests")
        interests = []
        if isinstance(raw_interests, list):
            seen = set()
            for item in raw_interests:
                cleaned = str(item).strip()[:_MAX_INTEREST]
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    interests.append(cleaned)
                if len(interests) >= _MAX_INTERESTS:
                    break

        notes = str(body.get("notes") or "").strip()[:_MAX_NOTES]

        ok = users_store.set_onboarding(
            user_id,
            preferred_name=preferred_name,
            interests=interests,
            notes=notes,
        )
        if not ok:
            return jsonify({"error": "save_failed"}), 400
        return jsonify({"ok": True}), 200
