"""GET /api/features → {"hidden": [...]}: features the owner hid app-wide via SANDY_HIDDEN_FEATURES.

Keys are the iOS client's contract (Features/Daily/DailyView.swift); the backend only relays them.
"""

from __future__ import annotations

import os

from flask import jsonify

from app.api.auth_handlers import require_auth


def _hidden_features() -> list:
    raw = os.getenv("SANDY_HIDDEN_FEATURES", "")
    return sorted({p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()})


def register_features_api(app):
    @app.route("/api/features", methods=["GET"])
    @require_auth
    def api_features(claims):
        return jsonify({"hidden": _hidden_features()}), 200
