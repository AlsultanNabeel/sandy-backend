"""Share API — interesting content Sandy surfaces from your own interests.

The REST face of the agent's ``share_interesting_content`` tool
(``app.agent.tools.schemas.content_share_tools``): that tool picks a topic from
the user's top tracked interests (``interests_tracker.get_top_interests``) and
hands it to ``research_web`` for a chatty, LLM-summarized reply inside an agent
session. A REST surface can't reuse that summarized reply (it needs a live
``DispatchContext`` + agent run), so — exactly like ``research_api`` does for the
Search tab — we reuse the tool's *logic* (same interest selection) but return the
underlying structured Exa results as content cards, with no LLM step.

Saved cards live in a small per-user store, ``sandy_shared_content`` (one doc per
saved item, ``chat_id`` == user_id, mirroring ``memory_api``'s shape). Real data
only; guests are fail-closed (empty / forbidden).

Endpoints:
  GET    /api/share/suggest        suggested content for the user's top interest
  GET    /api/share/saved          this user's saved content cards
  POST   /api/share/saved          save one card
  DELETE /api/share/saved/<id>     remove one saved card

Caveat: the agent tool's social-posting cousins (actually *sending* content to a
platform) are out of scope here — this surface only suggests, saves and removes.
"""

from __future__ import annotations

import os

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)

_COLL = "sandy_shared_content"


def _is_guest(claims) -> bool:
    return claims.get("role", "guest") == "guest"


def _topic_for(uid, mongo_db, explicit):
    """Same selection the tool uses: explicit topic, else the top interest."""
    topic = (explicit or "").strip()
    if topic or mongo_db is None:
        return topic
    from app.agent.interests_tracker import get_top_interests

    # In REST the active profile's chat_id is the user_id for both keys.
    tops = get_top_interests(uid, uid, mongo_db, limit=1)
    return tops[0] if tops else ""


def register_share_api(app, mongo_db=None):
    @app.route("/api/share/suggest", methods=["GET"])
    @require_auth
    def api_share_suggest(claims):
        # Guests have no tracked interests — fail closed with an empty payload.
        if _is_guest(claims):
            return jsonify({"topic": "", "items": [], "demo": True}), 200
        if mongo_db is None:
            return jsonify({"topic": "", "items": []}), 200

        explicit = (request.args.get("topic") or "").strip()
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"topic": "", "items": []}), 200
            topic = _topic_for(uid, mongo_db, explicit)

        if not topic:
            # No interests tracked yet — let the client show its warm hint.
            return jsonify({"topic": "", "items": []}), 200

        # Reuse the tool's query shape, but return structured cards (no LLM).
        from app.integrations.exa_client import search_exa

        key = os.getenv("EXA_API_KEY", "").strip()
        items = search_exa(f"معلومات مثيرة عن {topic}", key, num_results=8)
        return jsonify({"topic": topic, "items": items}), 200

    @app.route("/api/share/saved", methods=["GET"])
    @require_auth
    def api_share_saved(claims):
        if mongo_db is None or _is_guest(claims):
            return jsonify({"items": []}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"items": []}), 200
            items = []
            cur = (
                mongo_db[_COLL]
                .find(
                    {"chat_id": uid},
                    {"title": 1, "url": 1, "text": 1, "topic": 1},
                )
                .sort("created_at", -1)
                .limit(200)
            )
            for d in cur:
                items.append({
                    "id": str(d["_id"]),
                    "title": (d.get("title") or "").strip(),
                    "url": (d.get("url") or "").strip(),
                    "text": (d.get("text") or "").strip(),
                    "topic": (d.get("topic") or "").strip(),
                })
        return jsonify({"items": items}), 200

    @app.route("/api/share/saved", methods=["POST"])
    @require_auth
    def api_share_save(claims):
        if _is_guest(claims):
            return jsonify({"error": "forbidden"}), 403
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        body = request.get_json(silent=True) or {}
        url = (body.get("url") or "").strip()
        title = (body.get("title") or "").strip()
        if not url and not title:
            return jsonify({"error": "title_or_url_required"}), 400
        from datetime import datetime, timezone

        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            res = mongo_db[_COLL].insert_one({
                "chat_id": uid,
                "title": title,
                "url": url,
                "text": (body.get("text") or "").strip(),
                "topic": (body.get("topic") or "").strip(),
                "created_at": datetime.now(timezone.utc),
            })
        return jsonify({"ok": True, "id": str(res.inserted_id)}), 200

    @app.route("/api/share/saved/<item_id>", methods=["DELETE"])
    @require_auth
    def api_share_delete(claims, item_id):
        if _is_guest(claims):
            return jsonify({"error": "forbidden"}), 403
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(item_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            res = mongo_db[_COLL].delete_one({"_id": oid, "chat_id": uid})
        return jsonify({"ok": res.deleted_count > 0}), 200
