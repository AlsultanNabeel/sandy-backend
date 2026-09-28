"""GET /api/insights/weekly?lang=ar|en — this week vs last; guests get a demo payload."""

from __future__ import annotations

import logging

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)

logger = logging.getLogger(__name__)


def _lang() -> str:
    return "en" if (request.args.get("lang") or "").lower().startswith("en") else "ar"


def register_insights_api(app, mongo_db=None):
    from app.features import insights

    if mongo_db is not None:
        try:
            # Cached sentences are per ISO week; three weeks is plenty.
            mongo_db[insights.CACHE_COLL].create_index(
                "created_at", expireAfterSeconds=60 * 60 * 24 * 21, background=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[insights] index skipped: %s", exc)

    @app.route("/api/insights/weekly", methods=["GET"])
    @require_auth
    def api_insights_weekly(claims):
        lang = _lang()
        if claims.get("role") == "guest":
            return jsonify(insights.demo_summary(lang)), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify(insights.demo_summary(lang)), 200
            return jsonify(insights.weekly_summary(uid, lang)), 200
