"""GET /api/account, POST /api/account/reset {confirm:"RESET"}, DELETE /api/account {confirm:"DELETE"}.

Delete is a real delete, and unpairs the user's robots so the hardware stays reusable.
"""

from __future__ import annotations

import logging

from flask import jsonify, request

from app.api.auth_handlers import require_tenant

logger = logging.getLogger(__name__)

# Shown by the app as they are. An erase is safe to ask again: it carries on from what is left.
_PARTIAL_RESET = "ما انمسح كل شي، في جزء ضل. جرّب كمان مرّة وبكمّل من وين وقفت."
_PARTIAL_DELETE = "ما انحذف كل شي، في جزء ضل وحسابك لسا موجود. جرّب الحذف كمان مرّة وبكمّل من وين وقفت."


def register_account_api(app):
    @app.route("/api/account", methods=["GET"])
    @require_tenant
    def api_account_get(claims):
        from app.features import users_store
        from app.features.node_store import list_nodes

        uid = str(claims.get("user_id") or "")
        user = users_store.get_user(uid) or {}
        return jsonify({
            "user_id": uid,
            "email": user.get("email") or "",
            "provider": user.get("provider") or "",
            "created_at": str(user.get("created_at") or ""),
            "nodes": [
                {"node_id": n.get("node_id"), "label": n.get("label"),
                 "online": n.get("online")}
                for n in (list_nodes() or [])
            ],
        }), 200

    @app.route("/api/account/reset", methods=["POST"])
    @require_tenant
    def api_account_reset(claims):
        """Clear everything the account holds but keep the account and its robots."""
        body = request.get_json(silent=True) or {}
        if str(body.get("confirm") or "") != "RESET":
            return jsonify({"error": "confirm_required"}), 400
        uid = str(claims.get("user_id") or "")
        if not uid:
            return jsonify({"error": "no_user"}), 400

        from app.features.account_delete import wipe_account_data
        r = wipe_account_data(uid)
        if not r.get("ok"):
            return jsonify({**r, "message": _PARTIAL_RESET}), 500
        return jsonify(r), 200

    @app.route("/api/account", methods=["DELETE"])
    @require_tenant
    def api_account_delete(claims):
        """Erase the account; the confirmation string guards the one call with no undo."""
        body = request.get_json(silent=True) or {}
        if str(body.get("confirm") or "") != "DELETE":
            return jsonify({"error": "confirm_required"}), 400

        uid = str(claims.get("user_id") or "")
        if not uid:
            return jsonify({"error": "no_user"}), 400

        # Release the hardware first: a half-deleted account must not keep a robot claimed.
        from app.features.node_store import list_nodes, unpair_node
        for n in list_nodes() or []:
            unpair_node(str(n.get("node_id") or ""))

        from app.features.account_delete import delete_account
        r = delete_account(uid)
        if not r.get("ok"):
            return jsonify({**r, "message": _PARTIAL_DELETE}), 500
        return jsonify(r), 200
