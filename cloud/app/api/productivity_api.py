"""Web API for reminders and tasks — native MongoDB stores.

Every signed-in user (owner or regular app user) gets real CRUD against
sandy_reminders/sandy_tasks, scoped to their own ``user_id`` — the same
collections the Telegram bot and the voice channel use. A guest (visitor page)
sees the same tabs but with obviously-fake demo data, so the page looks alive
without exposing anything private.

All store calls run inside ``active_user_profile_context(build_user_profile(...))``
so the stores' ``current_user_id()`` resolves to THIS caller and every read/write
is isolated per user. It's the same wiring the web chat pipeline uses.
"""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import active_user_profile_context, build_user_profile

# Allowed task priorities; anything else falls back to "normal".
_PRIORITIES = {"low", "normal", "high"}


def _clean_priority(value) -> str:
    p = str(value or "").strip().lower()
    return p if p in _PRIORITIES else "normal"


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"


def _guest_forbidden():
    """Guests get read-only demo tabs — block every mutating endpoint."""
    return jsonify({"error": "forbidden"}), 403


# Fake data so a visitor's tab mirrors the owner's layout without leaking the
# real reminders/tasks. The frontend hides every add/edit/delete control when
# ``demo`` is true.
_DEMO_REMINDERS = [
    {"id": "demo-r1", "text": "موعد طبيب الأسنان", "remind_at": "2026-06-05T16:00:00", "is_recurring": False},
    {"id": "demo-r2", "text": "اتصل بأحمد بخصوص المشروع", "remind_at": "2026-06-06T11:30:00", "is_recurring": False},
    {"id": "demo-r3", "text": "تمرين رياضة صباحي", "remind_at": "2026-06-07T07:00:00", "is_recurring": True},
]
_DEMO_TASKS = [
    {"id": "demo-t1", "text": "تجهيز العرض التقديمي", "done": False, "due_at": "2026-06-05T00:00:00"},
    {"id": "demo-t2", "text": "شراء هدية عيد الميلاد", "done": False, "due_at": ""},
]
_DEMO_TASKS_DONE = [
    {"id": "demo-d1", "text": "إرسال الفاتورة الشهرية", "done": True, "due_at": ""},
    {"id": "demo-d2", "text": "مراجعة التقرير الشهري", "done": True, "due_at": ""},
]


def register_productivity_api(app, mongo_db=None):
    # Reminders (native store)
    @app.route("/api/reminders", methods=["GET"])
    @require_auth
    def api_list_reminders(claims):
        if _is_guest(claims):
            return jsonify({"items": _DEMO_REMINDERS, "demo": True}), 200
        from app.features.reminders_store import list_sandy_reminders
        with active_user_profile_context(build_user_profile(claims)):
            items = list_sandy_reminders(max_results=50)
        slim = [
            {
                "id": r.get("id", ""),
                "text": r.get("text", ""),
                "remind_at": r.get("remind_at", ""),
                "is_recurring": bool(r.get("is_recurring", False)),
                "note": r.get("note", "") or "",
            }
            for r in items
            if r.get("id")
        ]
        return jsonify({"items": slim, "demo": False}), 200

    @app.route("/api/reminders", methods=["POST"])
    @require_auth
    def api_add_reminder(claims):
        if _is_guest(claims):
            return _guest_forbidden()
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        remind_at = (body.get("remind_at") or "").strip()
        note = (body.get("note") or "").strip()
        if not text or not remind_at:
            return jsonify({"error": "text_and_remind_at_required"}), 400
        from app.features.reminders_store import add_reminder
        with active_user_profile_context(build_user_profile(claims)):
            res = add_reminder(
                text=text,
                remind_at_iso=remind_at,
                recurrence=(body.get("recurrence") or "").strip(),
                note=note,
            )
        if res.get("success"):
            return jsonify({"ok": True}), 200
        return jsonify({"error": res.get("error", "failed")}), 400

    @app.route("/api/reminders/<reminder_id>", methods=["DELETE"])
    @require_auth
    def api_delete_reminder(reminder_id, claims):
        if _is_guest(claims):
            return _guest_forbidden()
        from app.features.reminders_store import delete_reminder
        with active_user_profile_context(build_user_profile(claims)):
            ok = delete_reminder(reminder_id)
        return jsonify({"ok": bool(ok)}), (200 if ok else 400)

    # Tasks (native store)
    @app.route("/api/tasks", methods=["GET"])
    @require_auth
    def api_list_tasks(claims):
        completed = request.args.get("completed") in ("1", "true", "yes")
        if _is_guest(claims):
            demo = _DEMO_TASKS_DONE if completed else _DEMO_TASKS
            return jsonify({"items": demo, "demo": True}), 200
        from app.features.tasks_store import load_tasks, load_completed_tasks
        with active_user_profile_context(build_user_profile(claims)):
            items = (
                load_completed_tasks(mongo_db=mongo_db)
                if completed
                else load_tasks(mongo_db=mongo_db)
            )
        slim = [
            {
                "id": t.get("id", ""),
                "text": t.get("text", ""),
                "done": bool(t.get("done", False)),
                "due_at": t.get("due_at") or t.get("due") or "",
                "note": t.get("notes", "") or "",
                "priority": _clean_priority(t.get("priority")),
            }
            for t in items
            if t.get("id")
        ]
        return jsonify({"items": slim, "demo": False}), 200

    @app.route("/api/tasks", methods=["POST"])
    @require_auth
    def api_add_task(claims):
        if _is_guest(claims):
            return _guest_forbidden()
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        due = (body.get("due") or "").strip()
        note = (body.get("note") or "").strip()
        priority = _clean_priority(body.get("priority"))
        if not text:
            return jsonify({"error": "text_required"}), 400
        from app.features.tasks_store import add_task
        with active_user_profile_context(build_user_profile(claims)):
            tid = add_task(
                text,
                due_iso=due,
                notes=note,
                priority=priority,
                mongo_db=mongo_db,
            )
        if tid:
            return jsonify({"ok": True, "id": tid}), 200
        return jsonify({"error": "failed"}), 400

    @app.route("/api/tasks/<task_id>", methods=["PATCH"])
    @require_auth
    def api_update_task(task_id, claims):
        if _is_guest(claims):
            return _guest_forbidden()
        body = request.get_json(silent=True) or {}
        from app.features.tasks_store import (
            rename_task, complete_task, uncomplete_task,
            replace_task_note, set_task_priority,
        )
        ok = True
        with active_user_profile_context(build_user_profile(claims)):
            new_text = (body.get("text") or "").strip()
            if new_text:
                ok = rename_task(task_id, new_text, mongo_db=mongo_db) and ok
            if "note" in body:
                note = (body.get("note") or "").strip()
                ok = replace_task_note(task_id, note, mongo_db=mongo_db) and ok
            if "priority" in body:
                priority = _clean_priority(body.get("priority"))
                ok = set_task_priority(task_id, priority, mongo_db=mongo_db) and ok
            if "done" in body:
                if body.get("done"):
                    ok = complete_task(task_id, mongo_db=mongo_db) and ok
                else:
                    ok = uncomplete_task(task_id, mongo_db=mongo_db) and ok
        return jsonify({"ok": bool(ok)}), (200 if ok else 400)

    @app.route("/api/tasks/<task_id>", methods=["DELETE"])
    @require_auth
    def api_delete_task(task_id, claims):
        if _is_guest(claims):
            return _guest_forbidden()
        from app.features.tasks_store import delete_task
        with active_user_profile_context(build_user_profile(claims)):
            ok = delete_task(task_id, mongo_db=mongo_db)
        return jsonify({"ok": bool(ok)}), (200 if ok else 400)
