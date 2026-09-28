"""Digital gifts (poem, quote, motivation, smile, joke, riddle) kept in sandy_gifts.

Content comes from the digital_gift tool's LLM helper; a gift may carry a
``scheduled_at`` date for the app to show.

  GET /api/gifts · POST /api/gifts · POST /api/gifts/generate · DELETE /api/gifts/<gift_id>
"""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.tenant_db import scoped
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)

_COLL = "sandy_gifts"

# Must match the agent tool's enum.
_GIFT_KINDS = {"poem", "quote", "motivation", "smile", "joke", "riddle"}


def _clean_kind(value) -> str:
    kind = str(value or "smile").strip().lower()
    return kind if kind in _GIFT_KINDS else "smile"


def register_gifts_api(app, mongo_db=None):
    @app.route("/api/gifts", methods=["GET"])
    @require_auth
    def get_gifts(claims):
        if mongo_db is None:
            return jsonify({"items": []}), 200
        with active_user_profile_context(build_user_profile(claims)):
            coll = scoped(mongo_db, _COLL, field="chat_id")
            if coll is None:
                return jsonify({"items": []}), 200
            items = []
            cur = (
                coll
                .find({})
                .sort("created_at", -1)
                .limit(300)
            )
            for d in cur:
                items.append({
                    "id": str(d["_id"]),
                    "kind": d.get("kind", "smile"),
                    "recipient": d.get("recipient", ""),
                    "occasion": d.get("occasion", ""),
                    "content": d.get("content", ""),
                    "scheduled_at": d.get("scheduled_at", ""),
                })
        return jsonify({"items": items}), 200

    @app.route("/api/gifts", methods=["POST"])
    @require_auth
    def add_gift(claims):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        body = request.get_json(silent=True) or {}
        recipient = (body.get("recipient") or "").strip()
        occasion = (body.get("occasion") or "").strip()
        if not recipient or not occasion:
            return jsonify({"error": "recipient_and_occasion_required"}), 400
        from datetime import datetime, timezone

        with active_user_profile_context(build_user_profile(claims)):
            coll = scoped(mongo_db, _COLL, field="chat_id")
            if coll is None:
                return jsonify({"ok": False}), 403
            res = coll.insert_one({
                "kind": _clean_kind(body.get("kind")),
                "recipient": recipient,
                "occasion": occasion,
                "content": (body.get("content") or "").strip(),
                "scheduled_at": (body.get("scheduled_at") or "").strip(),
                "created_at": datetime.now(timezone.utc),
            })
        return jsonify({"ok": True, "id": str(res.inserted_id)}), 200

    @app.route("/api/gifts/generate", methods=["POST"])
    @require_auth
    def generate_gift(claims):
        """Ask Sandy to write a gift; stateless (POST /api/gifts to keep it)."""
        body = request.get_json(silent=True) or {}
        kind = _clean_kind(body.get("kind"))
        bits = [
            (body.get("recipient") or "").strip(),
            (body.get("occasion") or "").strip(),
        ]
        context = " — ".join(b for b in bits if b)
        with active_user_profile_context(build_user_profile(claims)):
            if not current_user_id():
                return jsonify({"content": ""}), 403
            from app.api.metering import meter_claims
            refusal = meter_claims(claims)
            if refusal:
                return jsonify(refusal[0]), refusal[1]
            from app.agent.tools.schemas.gift_tools import _generate_with_llm

            content = _generate_with_llm(kind, context) or ""
        return jsonify({"content": content}), 200

    @app.route("/api/gifts/<gift_id>", methods=["DELETE"])
    @require_auth
    def delete_gift(claims, gift_id):
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(gift_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        with active_user_profile_context(build_user_profile(claims)):
            coll = scoped(mongo_db, _COLL, field="chat_id")
            if coll is None:
                return jsonify({"ok": False}), 403
            res = coll.delete_one({"_id": oid})
        return jsonify({"ok": res.deleted_count > 0}), 200
