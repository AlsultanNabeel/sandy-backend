"""The owner's pages: the turn trace and what was spent (`features/trace_store.py`).

Only the accounts in SANDY_OWNER_ACCOUNTS; anyone else is answered 404, as if the routes
were not there. The list never carries words; one turn carries them only when it is the
owner's own.

    GET /api/owner/traces?limit=&user=&source=   → {"traces": [...]}
    GET /api/owner/traces/<id>                   → the turn
    GET /api/owner/costs?days=30                 → {"days", "total_usd", "by_user",
                                                    "by_source", "by_task"}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.api.metering import is_owner_account
from app.features import trace_store


def _iso(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def _bounded(name: str, default: int, top: int):
    raw = request.args.get(name, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if 1 <= value <= top else None


def _not_found():
    return jsonify({"error": "not_found"}), 404


def _bad(name: str, top: int):
    return jsonify({"error": "bad_request",
                    "message": f"«{name}» لازم يكون رقم من واحد لـ {top}."}), 400


def register_owner_api(app):
    @app.route("/api/owner/traces", methods=["GET"])
    @require_auth
    def api_owner_traces(claims):
        owner = str(claims.get("user_id") or "")
        if not is_owner_account(owner):
            return _not_found()
        limit = _bounded("limit", 50, 200)
        if limit is None:
            return _bad("limit", 200)
        rows = trace_store.list_traces(owner, limit=limit, user=request.args.get("user") or None,
                                       source=request.args.get("source") or None)
        return jsonify({"traces": [_iso(r) for r in rows]}), 200

    @app.route("/api/owner/traces/<trace_id>", methods=["GET"])
    @require_auth
    def api_owner_trace(claims, trace_id):
        owner = str(claims.get("user_id") or "")
        if not is_owner_account(owner):
            return _not_found()
        row = trace_store.get_trace(owner, trace_id)
        return (jsonify(_iso(row)), 200) if row else _not_found()

    @app.route("/api/owner/costs", methods=["GET"])
    @require_auth
    def api_owner_costs(claims):
        if not is_owner_account(str(claims.get("user_id") or "")):
            return _not_found()
        days = _bounded("days", 30, 366)
        if days is None:
            return _bad("days", 366)
        return jsonify(trace_store.costs(days=days)), 200
