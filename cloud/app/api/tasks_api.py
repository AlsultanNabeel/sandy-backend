"""The app's Tasks screen, behind the `tasks` switch (404 without it, like no such screen).

  GET    /api/scheduled-tasks                 {tasks: [{id, title, instructions, every_minutes,
                                               status (running | paused), next_at, failures,
                                               last_error, last_result, unseen}]}
  GET    /api/scheduled-tasks/<id>/results    {results: [{id, title, body, at, seen}]}, newest first
  POST   /api/scheduled-tasks/<id>/seen       all of it seen («صباح الخير» no longer tells it)
  POST   /api/scheduled-tasks/<id>/pause | /resume
  DELETE /api/scheduled-tasks/<id>            the task, what it saw and its results
  GET    /api/notify/email                    {address, confirmed, ready}: where results go
  POST   /api/notify/email                    {address}: a link goes to it (`notify/mail.py`)
  DELETE /api/notify/email                    no more emails
  GET    /api/notify/email/confirm?t=         the link itself, opened signed out: a small page

(`/api/tasks` was the old to-do list's, and stays retired.)

Every route but the link is the caller's own tenant; another user's task is 404.
"""

from __future__ import annotations

import functools
import html
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Response, jsonify, request

from app import notify
from app.api.auth_handlers import require_tenant
from app.blocks import tasks
from app.brain import lang
from app.notify import mail

logger = logging.getLogger(__name__)

_MAIL_ERRORS = {"bad_address": 400, "too_soon": 429, "not_set_up": 503}


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _switched(view):
    """Runs in the caller's tenant, only for an account with the switch on."""
    @functools.wraps(view)
    def wrapped(*args, claims, **kwargs):
        from app.utils import flags
        if not flags.on(tasks.SWITCH, claims.get("user_id") or ""):
            return jsonify({"error": "not_found"}), 404
        return view(*args, claims=claims, **kwargs)
    return require_tenant(wrapped)


def _missing():
    return jsonify({"error": "not_found", "message": lang.say("task_not_found")}), 404


def _shown(row: Dict[str, Any], unseen: Dict[str, int]) -> Dict[str, Any]:
    saw = tasks.state(row["id"])
    return {"id": row["id"], "title": row.get("text", ""),
            "instructions": (row.get("payload") or {}).get("instructions", ""),
            "every_minutes": tasks.every_minutes(row),
            "status": "paused" if row.get("status") == "paused" else "running",
            "next_at": _iso(row.get("fire_at")), "failures": int(saw.get("failures") or 0),
            "last_error": saw.get("last_error") or "", "last_result": saw.get("last_result") or "",
            "unseen": unseen.get(row["id"], 0)}


def _page(text: str, status: int) -> Response:
    body = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>Sandy</title>'
            f'<body style="font-family:-apple-system,sans-serif;padding:32px;font-size:18px;'
            f'line-height:1.6" dir="auto">{html.escape(text).replace(chr(10), "<br>")}</body>')
    return Response(body, status=status, mimetype="text/html")


def register_tasks_api(app):
    @app.route("/api/scheduled-tasks", methods=["GET"])
    @_switched
    def api_tasks_list(claims):
        unseen = notify.unseen_by_task()
        return jsonify({"tasks": [_shown(r, unseen) for r in tasks.running()]}), 200

    @app.route("/api/scheduled-tasks/<task_id>/results", methods=["GET"])
    @_switched
    def api_task_results(claims, task_id):
        if not tasks.get(task_id):
            return _missing()
        rows = notify.of_task(task_id)
        return jsonify({"results": [{"id": r["id"], "title": r.get("title", ""),
                                     "body": r.get("body", ""), "at": _iso(r.get("at")),
                                     "seen": bool(r.get("seen"))} for r in rows]}), 200

    @app.route("/api/scheduled-tasks/<task_id>/seen", methods=["POST"])
    @_switched
    def api_task_seen(claims, task_id):
        if not tasks.get(task_id):
            return _missing()
        notify.seen_all(task_id)
        return jsonify({"ok": True}), 200

    @app.route("/api/scheduled-tasks/<task_id>/pause", methods=["POST"])
    @_switched
    def api_task_pause(claims, task_id):
        return jsonify({"ok": True}) if tasks.pause(task_id) else _missing()

    @app.route("/api/scheduled-tasks/<task_id>/resume", methods=["POST"])
    @_switched
    def api_task_resume(claims, task_id):
        return jsonify({"ok": True}) if tasks.resume(task_id) else _missing()

    @app.route("/api/scheduled-tasks/<task_id>", methods=["DELETE"])
    @_switched
    def api_task_delete(claims, task_id):
        return jsonify({"ok": True}) if tasks.remove(task_id) else _missing()

    @app.route("/api/notify/email", methods=["GET"])
    @_switched
    def api_notify_email(claims):
        return jsonify(mail.status(claims.get("user_id") or "")), 200

    @app.route("/api/notify/email", methods=["POST"])
    @_switched
    def api_notify_email_set(claims):
        address = str((request.get_json(silent=True) or {}).get("address") or "")
        try:
            state = mail.ask_to_confirm(claims.get("user_id") or "", address)
        except (ValueError, RuntimeError) as exc:
            code = str(exc) if str(exc) in _MAIL_ERRORS else "bad_address"
            return jsonify({"error": code, "message": lang.say(f"mail_{code}")}), _MAIL_ERRORS[code]
        except OSError:
            logger.exception("[mail] the confirmation link did not leave")
            return jsonify({"error": "not_sent", "message": lang.say("mail_not_sent")}), 502
        return jsonify({"ok": True, "state": state}), 200

    @app.route("/api/notify/email", methods=["DELETE"])
    @_switched
    def api_notify_email_forget(claims):
        mail.forget(claims.get("user_id") or "")
        return jsonify({"ok": True}), 200

    @app.route("/api/notify/email/confirm", methods=["GET"])
    def api_notify_email_confirm():
        uid = mail.confirm(request.args.get("t", ""))
        if not uid:
            # Whose link it was is not known: both languages.
            dead = [lang.PHRASES["mail_link_dead_page"][x] for x in (lang.AR, lang.EN)]
            return _page("\n\n".join(dead), 400)
        with lang.using(lang.for_user(uid)):
            return _page(lang.say("mail_confirmed_page"), 200)
