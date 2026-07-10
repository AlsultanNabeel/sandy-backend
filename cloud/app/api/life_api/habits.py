"""حياتي API — habits routes."""
from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.api.life_api._common import _DEMO, _is_guest
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def _register_habits(app):
    # ── العادات ─────────────────────────────────────────────────────────
    @app.route("/api/life/habits", methods=["GET"])
    @require_auth
    def api_habits_list(claims):
        if _is_guest(claims):
            return jsonify({"items": _DEMO["habits"], "demo": True}), 200
        from app.features.habits_store import list_habits

        with active_user_profile_context(build_user_profile(claims)):
            items = list_habits()
        return jsonify({"items": items, "demo": False}), 200

    @app.route("/api/life/habits", methods=["POST"])
    @require_tenant
    def api_habits_add(claims):
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name_required"}), 400
        from app.features.habits_store import add_habit

        ok = add_habit(name)
        return jsonify({"ok": ok}), 200

    @app.route("/api/life/habits/checkin", methods=["POST"])
    @require_tenant
    def api_habits_checkin(claims):
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        from app.features.habits_store import checkin

        r = checkin(name)
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/habits/uncheckin", methods=["POST"])
    @require_tenant
    def api_habits_uncheckin(claims):
        body = request.get_json(silent=True) or {}
        habit_id = (body.get("id") or "").strip()
        from app.features.habits_store import uncheckin

        r = uncheckin(habit_id)
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/habits/detail", methods=["GET"])
    @require_tenant
    def api_habits_detail(claims):
        habit_id = (request.args.get("id") or "").strip()
        from app.features.habits_store import habit_history

        r = habit_history(habit_id)
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/habits/<habit_id>", methods=["PATCH"])
    @require_tenant
    def api_habits_rename(habit_id, claims):
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        from app.features.habits_store import rename_habit

        ok = rename_habit(habit_id, name)
        return jsonify({"ok": ok}), (200 if ok else 400)

    @app.route("/api/life/habits/<habit_id>", methods=["DELETE"])
    @require_tenant
    def api_habits_delete(habit_id, claims):
        from app.features.habits_store import delete_habit

        ok = delete_habit(habit_id)
        return jsonify({"ok": ok}), (200 if ok else 404)
