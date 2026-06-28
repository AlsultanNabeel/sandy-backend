"""Weather API — current conditions for a city, for the app's Weather screen.

Thin REST wrapper over ``app.features.weather.get_weather`` (the SAME helper the
agent's ``get_weather`` tool calls). Location is a free-text ``city`` query
param; when it's omitted we fall back to the feature's own default city. The
underlying helper appends the country and talks to wttr.in, so no API key is
needed here — the key (if any) lives in the helper, server-side.

The helper returns today's snapshot only (current conditions + today's
max/min + sunset); there is no multi-day forecast, so the endpoint surfaces
exactly those fields, nothing invented.

Per-user pattern mirrors memory_api / life_api: every route is ``@require_auth``
and runs inside ``active_user_profile_context(build_user_profile(claims))`` so
it's scoped to the caller, and guests fail closed (no weather, no data leak).

Endpoint:
  GET /api/weather?city=<name>   current weather for that city (or the default)
"""

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
        # Guests are chat-only — no live weather, fail closed.
        if claims.get("role") == "guest":
            return jsonify({"error": "forbidden"}), 403

        from app.features.weather import get_weather

        # Location comes from the caller: a free-text city. Empty ⇒ let the
        # helper use its own default city (do NOT hardcode one here).
        city = (request.args.get("city") or "").strip()

        with active_user_profile_context(build_user_profile(claims)):
            data = get_weather(city) if city else get_weather()

        if not data:
            return jsonify({"error": "weather_unavailable"}), 502

        # Pass the helper's snapshot straight through (already a flat JSON dict:
        # temp_c, feels_like_c, humidity, description, max_temp_c, min_temp_c,
        # sunset, city). The resolved city echoes back so the app can show it.
        return jsonify(data), 200
