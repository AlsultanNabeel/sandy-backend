"""حياتي API — expenses routes."""
from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.api.life_api._common import _DEMO, _is_guest
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def _register_expenses(app):
    # ── المصاريف ────────────────────────────────────────────────────────
    @app.route("/api/life/expenses", methods=["GET"])
    @require_auth
    def api_expenses(claims):
        if _is_guest(claims):
            return jsonify({**_DEMO["expenses"], "demo": True}), 200
        from app.features.expenses_store import list_expenses, month_summary

        days = int(request.args.get("days", 30) or 30)
        with active_user_profile_context(build_user_profile(claims)):
            items = list_expenses(days=days, limit=50)
            summary = month_summary(days=days)
        return jsonify({"items": items, "summary": summary, "demo": False}), 200

    @app.route("/api/life/expenses", methods=["POST"])
    @require_tenant
    def api_expenses_add(claims):
        body = request.get_json(silent=True) or {}
        from app.features.expenses_store import add_expense

        ok = add_expense(
            body.get("amount", 0),
            note=(body.get("note") or "").strip(),
            category=(body.get("category") or "").strip(),
        )
        return jsonify({"ok": ok}), (200 if ok else 400)

    @app.route("/api/life/expenses/<expense_id>", methods=["PATCH"])
    @require_tenant
    def api_expenses_update(expense_id, claims):
        body = request.get_json(silent=True) or {}
        from app.features.expenses_store import update_expense

        # Field absent = leave unchanged; present = set it.
        ok = update_expense(
            expense_id,
            amount=body.get("amount") if "amount" in body else None,
            note=(body.get("note") or "").strip() if "note" in body else None,
            category=(body.get("category") or "").strip() if "category" in body else None,
        )
        return jsonify({"ok": ok}), (200 if ok else 400)

    @app.route("/api/life/expenses/<expense_id>", methods=["DELETE"])
    @require_tenant
    def api_expenses_delete(expense_id, claims):
        from app.features.expenses_store import delete_expense

        ok = delete_expense(expense_id)
        return jsonify({"ok": ok}), (200 if ok else 404)
