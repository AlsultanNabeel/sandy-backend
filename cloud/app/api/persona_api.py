"""Web API for per-user personality customization.

Every signed-in user (any tenant, not just the owner) can pick Sandy's dialect
and/or write custom instructions for her tone. Her Palestinian identity is NOT
part of this — it's appended unconditionally by
``app.agent.context_builder.build_effective_persona`` and can't be touched
here.

Two routes, both ``@require_auth`` (every signed-in user manages their own):
  GET  /api/persona → current dialect + custom instructions + available dialects
  POST /api/persona → save dialect and/or custom instructions
                       ({"custom_instructions": ""} resets to the default persona)
"""

from __future__ import annotations

from flask import jsonify, request

from app.agent.context_builder import DIALECT_PRESETS
from app.api.auth_handlers import require_auth
from app.features import users_store

_MAX_CUSTOM_INSTRUCTIONS = 2000


def register_persona_api(app):
    @app.route("/api/persona", methods=["GET"])
    @require_auth
    def api_get_persona(claims):
        persona = users_store.get_persona(claims.get("user_id") or "")
        return jsonify({
            "dialect": persona["dialect"],
            "custom_instructions": persona["custom_instructions"],
            "dialects": [
                {"key": key, "label": preset["label"]}
                for key, preset in DIALECT_PRESETS.items()
            ],
        }), 200

    @app.route("/api/persona", methods=["POST"])
    @require_auth
    def api_save_persona(claims):
        user_id = claims.get("user_id") or ""
        if not user_id:
            return jsonify({"error": "no_user"}), 400

        body = request.get_json(silent=True) or {}

        dialect = None
        if "dialect" in body:
            dialect = str(body.get("dialect") or "").strip()
            if dialect not in DIALECT_PRESETS:
                return jsonify({"error": "invalid_dialect"}), 400

        custom_instructions = None
        if "custom_instructions" in body:
            custom_instructions = str(body.get("custom_instructions") or "").strip()
            if len(custom_instructions) > _MAX_CUSTOM_INSTRUCTIONS:
                return jsonify({"error": "too_long"}), 400

        ok = users_store.set_persona(
            user_id,
            dialect=dialect,
            custom_instructions=custom_instructions,
        )
        if not ok:
            return jsonify({"error": "save_failed"}), 400
        return jsonify({"ok": True}), 200
