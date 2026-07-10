"""حياتي API — shopping routes."""
from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.api.life_api._common import _DEMO, _is_guest
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def _register_shopping(app):
    # ── التسوق ──────────────────────────────────────────────────────────
    @app.route("/api/life/shopping", methods=["GET"])
    @require_auth
    def api_shopping_list(claims):
        if _is_guest(claims):
            return jsonify({"items": _DEMO["shopping"], "demo": True}), 200
        from app.features.shopping_store import list_items

        with active_user_profile_context(build_user_profile(claims)):
            items = list_items(include_bought=True)
        return jsonify({"items": items, "demo": False}), 200

    @app.route("/api/life/shopping", methods=["POST"])
    @require_tenant
    def api_shopping_add(claims):
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text_required"}), 400
        from app.features.shopping_store import add_item

        ok = add_item(text, category=(body.get("category") or "").strip())
        return jsonify({"ok": ok}), 200

    @app.route("/api/life/shopping/<item_id>", methods=["PATCH"])
    @require_tenant
    def api_shopping_check(item_id, claims):
        body = request.get_json(silent=True) or {}
        from app.features.shopping_store import check_item_by_id

        r = check_item_by_id(item_id, price=body.get("price"), qty=body.get("qty"))
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/shopping/<item_id>", methods=["DELETE"])
    @require_tenant
    def api_shopping_delete(item_id, claims):
        from app.features.shopping_store import delete_item_by_id

        ok = delete_item_by_id(item_id)
        return jsonify({"ok": ok}), (200 if ok else 404)

    @app.route("/api/life/shopping/<item_id>/price", methods=["POST"])
    @require_tenant
    def api_shopping_set_price(item_id, claims):
        body = request.get_json(silent=True) or {}
        from app.features.shopping_store import set_item_purchase

        ok = set_item_purchase(
            item_id,
            price=body.get("price"),
            qty=body.get("qty"),
            unit=body.get("unit"),
        )
        return jsonify({"ok": ok}), (200 if ok else 404)

    @app.route("/api/life/shopping/last-price", methods=["GET"])
    @require_tenant
    def api_shopping_last_price(claims):
        text = (request.args.get("text") or "").strip()
        from app.features.shopping_store import last_price_for

        price = last_price_for(text)
        return jsonify({"price": price}), 200
