"""Web API for first-open onboarding — native multi-user store.

A brand-new user opening the app for the first time answers a tiny
get-to-know-you flow (preferred name + interests). The answers live in the
``onboarding`` sub-doc of their ``sandy_users`` record (see
``app.features.users_store``) and feed straight into Sandy's per-user context so
she greets them by name and knows what they care about.

Two routes, both ``@require_auth`` (every signed-in user manages their own):
  GET  /api/onboarding → current onboarding state (empty defaults if unset)
  POST /api/onboarding → save preferred name + interests (+ optional notes)

Follows the same module shape as ``productivity_api`` — a single
``register_onboarding_api(app)`` that defines the routes. The app factory wires
it up; this module never registers itself.
"""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.features import users_store

_MAX_INTERESTS = 20


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

        preferred_name = str(body.get("preferred_name") or "").strip()

        raw_interests = body.get("interests")
        interests = []
        if isinstance(raw_interests, list):
            seen = set()
            for item in raw_interests:
                cleaned = str(item).strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    interests.append(cleaned)
                if len(interests) >= _MAX_INTERESTS:
                    break

        notes = str(body.get("notes") or "").strip()

        ok = users_store.set_onboarding(
            user_id,
            preferred_name=preferred_name,
            interests=interests,
            notes=notes,
        )
        if not ok:
            return jsonify({"error": "save_failed"}), 400
        return jsonify({"ok": True}), 200
