"""GET /api/weather?city=<name>: today's conditions via features.weather (default city if omitted)."""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
)


def register_weather_api(app, mongo_db=None):
    @app.route("/api/weather", methods=["GET"])
    @require_auth
    def get_weather_now(claims):
        if claims.get("role") == "guest":
            return jsonify({"error": "forbidden"}), 403

        from app.features.weather import get_weather

        # Empty ⇒ the helper's own default city.
        city = (request.args.get("city") or "").strip()

        with active_user_profile_context(build_user_profile(claims)):
            data = get_weather(city) if city else get_weather()

        if not data:
            return jsonify({"error": "weather_unavailable"}), 502

        return jsonify(data), 200
