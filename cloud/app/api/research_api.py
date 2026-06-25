"""External web-research API: web search + place search + page fetch.

A direct REST surface over the same engines the agent's research_web /
research_places / fetch_url tools use (Exa + Google Places) — but returns
structured results (titles / urls / snippets) with no LLM summarization and no
agent session, for the iOS Search tab.

Guest/authenticated split like the rest of the product: guests get a tiny static
demo payload (so visitors see the shape without burning Exa/Places quota); every
authenticated user runs a real search.

Endpoints:
  GET /api/research?q=...&kind=web|places   structured search results
  GET /api/research/page?url=...            fetch one page's contents (fetch_url)
"""

from __future__ import annotations

import os

from flask import jsonify, request

from app.api.auth_handlers import require_auth


def _is_guest(claims) -> bool:
    return claims.get("role", "guest") == "guest"


# Tiny static samples so visitors see the result shape without spending quota.
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

        if kind == "places":
            from app.features.google_places import search_places

            key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
            items = search_places(q, key, max_results=8)
            return jsonify({"kind": "places", "items": items, "demo": False}), 200

        from app.integrations.exa_client import search_exa

        key = os.getenv("EXA_API_KEY", "").strip()
        items = search_exa(q, key, num_results=8)
        return jsonify({"kind": "web", "items": items, "demo": False}), 200

    @app.route("/api/research/page", methods=["GET"])
    @require_auth
    def api_research_page(claims):
        url = (request.args.get("url") or "").strip()
        if not url:
            return jsonify({"error": "url_required"}), 400

        if _is_guest(claims):
            return jsonify({"item": {}, "demo": True}), 200

        from app.integrations.exa_client import get_exa_page_content

        key = os.getenv("EXA_API_KEY", "").strip()
        item = get_exa_page_content(url, key)
        return jsonify({"item": item, "demo": False}), 200
