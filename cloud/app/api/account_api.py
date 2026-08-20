"""Account lifecycle: know yourself, erase yourself.

Endpoints:
  GET    /api/account          -> {user_id, email, provider, created_at, nodes}
  DELETE /api/account          {confirm:"DELETE"}  -> erase everything

The delete is a real delete, not a flag. A Sandy account holds a voiceprint, a
journal, photos, spending and a transcript of every conversation its owner has
had with her — "deactivated" is not an honest answer to someone asking for that
to be gone.

It also unpairs their robots on the way out, which matters for a reason that is
easy to miss: a node claimed by a deleted account would stay claimed forever,
and the hardware would be permanently unpairable by anyone, including the person
holding it.
"""

from __future__ import annotations

import logging

from flask import jsonify, request

from app.api.auth_handlers import require_tenant

logger = logging.getLogger(__name__)


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
        """Empty the account without destroying it. "Start over."

        Distinct from delete for a reason the owner ran into immediately: he
        wanted a clean slate, not a new identity. Deleting the account would
        also drop his sign-in, his subscription, and his paired hardware — so
        "start fresh" would cost him the robot as well as the data.

        This clears everything the account *holds* — conversations, memory,
        tasks, journal, photos, voiceprint — and leaves the account and its
        robots exactly where they were.
        """
        body = request.get_json(silent=True) or {}
        if str(body.get("confirm") or "") != "RESET":
            return jsonify({"error": "confirm_required"}), 400
        uid = str(claims.get("user_id") or "")
        if not uid:
            return jsonify({"error": "no_user"}), 400

        from app.features.account_delete import wipe_account_data
        return jsonify(wipe_account_data(uid)), 200

    @app.route("/api/account", methods=["DELETE"])
    @require_tenant
    def api_account_delete(claims):
        """Erase the account. Requires an explicit confirmation string.

        The confirmation is not ceremony. This is the one call in the API with
        no undo, and it is reachable by any client holding a valid token — a
        mistyped path or a stray retry must not be able to trigger it.
        """
        body = request.get_json(silent=True) or {}
        if str(body.get("confirm") or "") != "DELETE":
            return jsonify({"error": "confirm_required"}), 400

        uid = str(claims.get("user_id") or "")
        if not uid:
            return jsonify({"error": "no_user"}), 400

        # Release the hardware first. If the wipe below fails halfway, a robot
        # that is already free can be re-paired; a robot still claimed by a
        # half-deleted account is a brick.
        from app.features.node_store import list_nodes, unpair_node
        for n in list_nodes() or []:
            # `unpair_node` بترجّع خطأ بالقاموس ما بترمي — فما في داعي لحارس.
            unpair_node(str(n.get("node_id") or ""))

        from app.features.account_delete import delete_account
        r = delete_account(uid)
        if not r.get("ok"):
            return jsonify(r), 500
        return jsonify(r), 200
