"""GET /api/research?q=...&kind=web|places — raw Exa / Google Places results for the iOS Search tab.

Guests get a static demo payload so they don't spend quota.
"""

from __future__ import annotations

import logging
import os

from flask import jsonify, request

from app.api.auth_handlers import require_auth

logger = logging.getLogger(__name__)


def _is_guest(claims) -> bool:
    return claims.get("role", "guest") == "guest"


_DEMO_WEB = [
    {
        "title": "نتيجة بحث تجريبية",
        "url": "https://example.com",
        "text": "هذه نتيجة تجريبية — سجّل دخولك ليبحث ساندي فعلياً على الويب.",
        "published_date": "",
    },
]
_DEMO_PLACES = [
    {
        "name": "مقهى تجريبي",
        "address": "وسط البلد",
        "rating": 4.5,
        "reviews_count": 120,
        "phone": "",
        "website": "",
        "price_level": "متوسط",
        "open_now": "مفتوح الآن",
        "maps_url": "",
    },
]


def register_research_api(app):
    @app.route("/api/research", methods=["GET"])
    @require_auth
    def api_research(claims):
        q = (request.args.get("q") or "").strip()
        kind = (request.args.get("kind") or "web").strip().lower()
        if not q:
            return jsonify({"error": "q_required"}), 400
        if kind not in ("web", "places"):
            kind = "web"

        if _is_guest(claims):
            demo = _DEMO_WEB if kind == "web" else _DEMO_PLACES
            return jsonify({"kind": kind, "items": demo, "demo": True}), 200

        from app.api.metering import meter_claims
        refusal = meter_claims(claims)
        if refusal:
            return jsonify(refusal[0]), refusal[1]

        if kind == "places":
            from app.features.google_places import PlacesUnavailable, search_places

            key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
            try:
                items = search_places(q, key, max_results=8)
            except PlacesUnavailable as exc:
                # 503, not an empty 200: "search didn't run" isn't "nothing found".
                logger.error("[research] places unavailable: %s", exc)
                return jsonify({"error": "places_unavailable"}), 503
            return jsonify({"kind": "places", "items": items, "demo": False}), 200

        from app.integrations.exa_client import INTERACTIVE_TIMEOUT_S, search_exa

        key = os.getenv("EXA_API_KEY", "").strip()
        items = search_exa(q, key, num_results=8, timeout=INTERACTIVE_TIMEOUT_S)
        return jsonify({"kind": "web", "items": items, "demo": False}), 200
