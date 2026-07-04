"""Feature visibility — the owner's central on/off switch (Phase 7).

Every optional feature (tabs/tools/archive entries) can be hidden app-wide from
here without a deploy of the client: set the ``SANDY_HIDDEN_FEATURES`` env var to
a comma-separated list of feature keys and they vanish from every app — and from
each user's in-app settings too (a user can only toggle features the owner still
allows). The client keeps ALL the code; this just decides what's shown.

  GET /api/features → {"hidden": ["habits","gifts",...]}

The key list is the client's contract (see FeatureFlags.swift on iOS); the
backend stays dumb on purpose — it just relays the owner's hidden set — so adding
a new feature never needs a backend change.
"""

from __future__ import annotations

import os

from flask import jsonify

from app.api.auth_handlers import require_auth


def _hidden_features() -> list:
    raw = os.getenv("SANDY_HIDDEN_FEATURES", "")
    # comma or whitespace separated, tolerant of stray spaces / empties
    return sorted({p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()})


def register_features_api(app):
    @app.route("/api/features", methods=["GET"])
    @require_auth
    def api_features(claims):
        return jsonify({"hidden": _hidden_features()}), 200
