"""Timeline API — one unified, time-ordered activity log across the user's data.

Aggregates the user's tasks, reminders, expenses and journal entries into a single
stream of events (newest first), each carrying its source type + id so the app can
act on it (delete via the source's own endpoint, jump to its tab to edit). Real
data only, scoped to the caller. No new storage — reads the existing per-feature
stores inside the caller's profile context.

Endpoint:
  GET /api/timeline   unified activity events {type,id,title,subtitle,ts,done}
"""

from __future__ import annotations

from datetime import datetime

from flask import jsonify

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def _iso(v) -> str:
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v) if v else ""


def _task_events():
    from app.features.tasks_store import load_completed_tasks, load_tasks
    out = []
    for t in load_tasks() + load_completed_tasks():
        done = bool(t.get("done"))
        ts = _iso(t.get("completed_at") if done else t.get("created_at")) \
            or _iso(t.get("created_at"))
        out.append({
            "type": "task", "id": str(t.get("id", "")),
            "title": t.get("text", ""), "subtitle": "",
            "ts": ts, "done": done,
        })
    return out


def _reminder_events():
    from app.features.reminders_store import load_reminders
    return [{
        "type": "reminder", "id": str(r.get("id", "")),
        "title": r.get("text", ""), "subtitle": "",
        "ts": _iso(r.get("remind_at") or r.get("created_at")),
        "done": False,
    } for r in load_reminders(max_results=100)]


def _expense_events():
    from app.features.expenses_store import list_expenses
    out = []
    for x in list_expenses(days=365, limit=200):
        amt = x.get("amount", 0)
        cat = x.get("category", "") or ""
        out.append({
            "type": "expense", "id": str(x.get("id", "")),
            "title": x.get("note", "") or "مصروف",
            "subtitle": f"{amt} {cat}".strip(),
            "ts": _iso(x.get("at")), "done": False,
        })
    return out


def _journal_events():
    from app.features.journal_store import recent_entries
    return [{
        "type": "journal", "id": str(j.get("id", "")),
        "title": j.get("text", ""), "subtitle": "",
        "ts": _iso(j.get("at") or j.get("date")), "done": False,
    } for j in recent_entries(limit=100)]


# Most events one response carries.
_MAX_EVENTS = 300


def register_timeline_api(app):
    @app.route("/api/timeline", methods=["GET"])
    @require_auth
    def get_timeline(claims):
        from app.utils.thread_pool import gather

        # The four sources are independent, so they are read at the same time
        # rather than one after another; `gather` carries the caller's tenant
        # into each job, and a source that fails contributes nothing (logged
        # there) instead of failing the whole timeline.
        with active_user_profile_context(build_user_profile(claims)):
            parts = gather({
                "tasks": _task_events,
                "reminders": _reminder_events,
                "expenses": _expense_events,
                "journal": _journal_events,
            })
        events = [e for part in parts.values() for e in (part or []) if e["ts"]]
        events.sort(key=lambda e: e["ts"], reverse=True)
        return jsonify({"items": events[:_MAX_EVENTS]}), 200
