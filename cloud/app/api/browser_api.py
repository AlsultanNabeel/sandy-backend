"""The browser's routes, behind the `browser` switch (404 without it, like no such screen).

  GET    /api/stop          {stopped}: the emergency stop (`features/stop_all`)
  POST   /api/stop          {stopped: true}: every task and browser job stops now
  DELETE /api/stop          {stopped: false}: it all goes on again

Every route is the caller's own tenant.
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify

from app.api.auth_handlers import require_tenant
from app.brain import lang
from app.features import stop_all

logger = logging.getLogger(__name__)


def _switched(view):
    """Runs in the caller's tenant, only for an account with the switch on."""
    @functools.wraps(view)
    def wrapped(*args, claims, **kwargs):
        from app.brain import tools_browser
        if not tools_browser.offered(claims.get("user_id") or ""):
            return jsonify({"error": "not_found"}), 404
        return view(*args, claims=claims, **kwargs)
    return require_tenant(wrapped)


def register_browser_api(app) -> None:
    @app.route("/api/stop", methods=["GET"])
    @_switched
    def stop_state(claims):
        return jsonify({"stopped": stop_all.stopped(claims["user_id"])})

    @app.route("/api/stop", methods=["POST"])
    @_switched
    def stop_now(claims):
        if not stop_all.stop(claims["user_id"]):
            return jsonify({"error": "unavailable", "message": lang.say("stop_failed")}), 503
        return jsonify({"stopped": True})

    @app.route("/api/stop", methods=["DELETE"])
    @_switched
    def stop_end(claims):
        if not stop_all.resume(claims["user_id"]):
            return jsonify({"error": "unavailable", "message": lang.say("stop_failed")}), 503
        return jsonify({"stopped": False})
