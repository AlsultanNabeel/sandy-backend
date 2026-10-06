"""GET /api/weather?city=<name>: today's conditions via features.weather (the user's home
city if omitted, 400 `city_required` when there is none); a city that answers is kept as
the user's home city."""

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

        from app.features import users_store
        from app.features.weather import get_weather, home_city

        # Empty ⇒ the user's home city.
        city = (request.args.get("city") or "").strip()
        uid = str(claims.get("user_id") or "")

        city_now = city or home_city(uid)
        if not city_now:
            return jsonify({"error": "city_required",
                            "message": "اختار مدينتك عشان أجيبلك الطقس."}), 400
        with active_user_profile_context(build_user_profile(claims)):
            data = get_weather(city_now)

        if not data:
            return jsonify({"error": "weather_unavailable"}), 502
        if city:
            # A city that answered is where Sandy looks when asked with none.
            users_store.set_city(uid, city)

        return jsonify(data), 200
