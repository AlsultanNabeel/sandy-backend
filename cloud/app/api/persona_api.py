"""GET/POST /api/persona: each user's dialect and custom instructions for Sandy.

Her Palestinian identity lock is added separately and can't be changed here.
{"custom_instructions": ""} resets to the default persona.
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
