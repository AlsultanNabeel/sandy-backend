"""حياتي API — journal routes."""
from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.api.life_api._common import _DEMO, _is_guest
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def _register_journal(app):
    # ── اليوميات ────────────────────────────────────────────────────────
    @app.route("/api/life/journal", methods=["GET"])
    @require_auth
    def api_journal(claims):
        if _is_guest(claims):
            return jsonify({"items": _DEMO["journal"], "demo": True}), 200
        from app.features.journal_store import recent_entries, search_entries

        q = (request.args.get("q") or "").strip()
        with active_user_profile_context(build_user_profile(claims)):
            items = search_entries(q) if q else recent_entries(limit=30)
        return jsonify({"items": items, "demo": False}), 200

    @app.route("/api/life/journal", methods=["POST"])
    @require_tenant
    def api_journal_add(claims):
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text_required"}), 400
        from app.features.journal_store import add_entry

        ok = add_entry(text)
        return jsonify({"ok": ok}), 200

    @app.route("/api/life/journal/<entry_id>", methods=["PATCH"])
    @require_tenant
    def api_journal_update(entry_id, claims):
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text_required"}), 400
        from app.features.journal_store import update_entry

        ok = update_entry(entry_id, text)
        return jsonify({"ok": ok}), (200 if ok else 400)

    @app.route("/api/life/journal/<entry_id>", methods=["DELETE"])
    @require_tenant
    def api_journal_delete(entry_id, claims):
        from app.features.journal_store import delete_entry

        ok = delete_entry(entry_id)
        return jsonify({"ok": ok}), (200 if ok else 404)
