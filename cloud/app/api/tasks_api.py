"""The app's Tasks screen, behind the `tasks` switch (404 without it, like no such screen).

  GET    /api/scheduled-tasks                 {tasks: [{id, title, instructions, every_minutes,
                                               status (running | paused), next_at, failures,
                                               last_error, last_result, unseen, delivery}]}
  GET    /api/scheduled-tasks/<id>/results    {results: [{id, title, body, at, seen}]}, newest first
  POST   /api/scheduled-tasks/<id>/seen       all of it seen («صباح الخير» no longer tells it)
  POST   /api/scheduled-tasks/<id>/preview    {every_minutes?, delivery?, instructions?, title?}:
                                               {summary, check?}: the question a change waits on,
                                               the same as by talk; new words bring their check
                                               (one model call, `tools_tasks.derive_check`); saves nothing
  PATCH  /api/scheduled-tasks/<id>            the same, plus the preview's `check`: saved
                                               (`tasks.edit`), {task}
  POST   /api/scheduled-tasks/<id>/pause | /resume
  DELETE /api/scheduled-tasks/<id>            the task, what it saw and its results
  GET    /api/notify/email                    {address, confirmed, ready}: where results go
  POST   /api/notify/email                    {address}: a link goes to it (`notify/mail.py`)
  DELETE /api/notify/email                    no more emails
  GET    /api/notify/task/open?t=             an email's «open the task»: a page that opens the app
  GET    /api/notify/task/stop?t=             an email's «stop the alerts»: a page with a button
  POST   /api/notify/task/stop                {t} (the button): the task paused
  GET    /api/notify/email/confirm?t=         the link itself, opened signed out: a small page
                                               with a «Confirm» button; opening it confirms nothing
  POST   /api/notify/email/confirm            {t} (the button): confirms it, once

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

_MAIL_ERRORS = {"bad_address": 400, "too_soon": 429, "too_many": 429, "not_set_up": 503}


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
    return jsonify({"error": "not_found", "message": lang.say("task_missing")}), 404


def _shown(row: Dict[str, Any], unseen: Dict[str, int]) -> Dict[str, Any]:
    saw = tasks.state(row["id"])
    return {"id": row["id"], "title": row.get("text", ""),
            "instructions": (row.get("payload") or {}).get("instructions", ""),
            "every_minutes": tasks.every_minutes(row),
            "status": "paused" if row.get("status") == "paused" else "running",
            "next_at": _iso(row.get("fire_at")), "failures": int(saw.get("failures") or 0),
            "last_error": saw.get("last_error") or "", "last_result": saw.get("last_result") or "",
            "unseen": unseen.get(row["id"], 0), "delivery": tasks.how(row)}


class _Bad(Exception):
    """A change that cannot be read: its code, said in his language."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _change(row: Dict[str, Any], body: Dict[str, Any], uid: str, *, derive: bool) -> Dict[str, Any]:
    """A change from the screen, read and checked: the values `tasks.edit` takes, and the
    question it waits on. A new check must read; new words with none get one (`derive`)."""
    from app.blocks.tasks import READ_TOOLS
    from app.brain import tools_tasks

    out: Dict[str, Any] = {}
    if "every_minutes" in body:
        every = body["every_minutes"]
        if not isinstance(every, int) or isinstance(every, bool) or every < 1:
            raise _Bad("bad_every")
        out["every"] = every
    if "delivery" in body:
        way = body["delivery"] if isinstance(body["delivery"], dict) else {}
        try:
            out["delivery"] = tasks.clean_delivery(way.get("mode"), way.get("hours"), way.get("at"))
        except ValueError:
            raise _Bad("bad_delivery") from None
    if "title" in body and str(body["title"] or "").strip():
        out["title"] = str(body["title"]).strip()[:120]
    if "instructions" in body:
        words = str(body["instructions"] or "").strip()
        if not words or len(words) > 2000:
            raise _Bad("bad_instructions")
        out["instructions"] = words
        check = body.get("check")
        if check is not None:
            if (not isinstance(check, dict) or check.get("tool") not in READ_TOOLS
                    or not isinstance(check.get("args", {}), dict)):
                raise _Bad("bad_check")
            out["probe"] = {"tool": check["tool"], "args": dict(check.get("args") or {})}
        elif derive:
            out["probe"] = tools_tasks.derive_check(words, uid)
            if out["probe"] is None:
                raise _Bad("check_failed", 503)
    if not out:
        raise _Bad("nothing_to_change")
    payload = row.get("payload") or {}
    out["summary"] = tools_tasks.edit_summary(
        row, title=out.get("title") or row.get("text", ""),
        instructions=out.get("instructions") or payload.get("instructions", ""),
        every=out.get("every") or tasks.every_minutes(row) or 1,
        delivery=out.get("delivery") or tasks.how(row))
    return out


def _bad(exc: _Bad):
    return jsonify({"error": exc.code, "message": lang.say(f"task_{exc.code}")}), exc.status


def _page(text: str, status: int, form: str = "") -> Response:
    body = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>Sandy</title>'
            f'<body style="font-family:-apple-system,sans-serif;padding:32px;font-size:18px;'
            f'line-height:1.6" dir="auto">{html.escape(text).replace(chr(10), "<br>")}{form}</body>')
    return Response(body, status=status, mimetype="text/html")


def _dead_link() -> Response:
    # Whose link it was is not known: both languages.
    dead = [lang.PHRASES["mail_link_dead_page"][x] for x in (lang.AR, lang.EN)]
    return _page("\n\n".join(dead), 400)


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

    @app.route("/api/scheduled-tasks/<task_id>/preview", methods=["POST"])
    @_switched
    def api_task_preview(claims, task_id):
        row = tasks.get(task_id)
        if not row:
            return _missing()
        try:
            change = _change(row, request.get_json(silent=True) or {}, claims.get("user_id") or "",
                             derive=True)
        except _Bad as exc:
            return _bad(exc)
        return jsonify({"summary": change["summary"], "check": change.get("probe")}), 200

    @app.route("/api/scheduled-tasks/<task_id>", methods=["PATCH"])
    @_switched
    def api_task_change(claims, task_id):
        row = tasks.get(task_id)
        if not row:
            return _missing()
        try:
            change = _change(row, request.get_json(silent=True) or {}, claims.get("user_id") or "",
                             derive=True)
        except _Bad as exc:
            return _bad(exc)
        change.pop("summary")
        tasks.edit(task_id, **change)
        return jsonify({"task": _shown(tasks.get(task_id), notify.unseen_by_task())}), 200

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

    def _linked_task(token: str):
        """(account, task row) of an email's signed link, in that account; None when not ours."""
        from app.utils.user_profiles import active_user_profile_context
        found = mail.read_task_link(token)
        if not found:
            return None, None
        uid, tid = found
        with active_user_profile_context({"chat_id": uid, "user_id": uid, "relation": "user",
                                          "permissions": "all"}):
            return uid, tasks.get(tid)

    @app.route("/api/notify/task/open", methods=["GET"])
    def api_notify_task_open():
        uid, row = _linked_task(request.args.get("t", ""))
        if not row:
            return _dead_link()
        target = f"sandy://tasks/{row['id']}"
        with lang.using(lang.for_user(uid)):
            link = (f'<p><a href="{html.escape(target, quote=True)}">'
                    f'{html.escape(lang.say("mail_open_task"))}</a></p>'
                    f'<meta http-equiv="refresh" content="0;url={html.escape(target, quote=True)}">')
            return _page(lang.say("mail_open_page"), 200, link)

    @app.route("/api/notify/task/stop", methods=["GET"])
    def api_notify_task_stop_page():
        """Opening it pauses nothing (a mail scanner opens links): a button."""
        token = request.args.get("t", "")
        uid, row = _linked_task(token)
        if not row:
            return _dead_link()
        with lang.using(lang.for_user(uid)):
            form = ('<form method="post" action="/api/notify/task/stop" style="margin-top:24px">'
                    f'<input type="hidden" name="t" value="{html.escape(token, quote=True)}">'
                    '<button type="submit" style="font-size:18px;padding:12px 32px;border-radius:12px;'
                    f'border:0;background:#0077B6;color:#fff">{html.escape(lang.say("mail_stop_task"))}'
                    '</button></form>')
            return _page(lang.say("mail_stop_page", title=row.get("text", "")), 200, form)

    @app.route("/api/notify/task/stop", methods=["POST"])
    def api_notify_task_stop():
        from app.utils.user_profiles import active_user_profile_context
        uid, row = _linked_task(request.form.get("t", ""))
        if not row:
            return _dead_link()
        with active_user_profile_context({"chat_id": uid, "user_id": uid, "relation": "user",
                                          "permissions": "all"}):
            tasks.pause(row["id"])
        with lang.using(lang.for_user(uid)):
            return _page(lang.say("mail_stopped_page", title=row.get("text", "")), 200)

    @app.route("/api/notify/email/confirm", methods=["GET"])
    def api_notify_email_confirm_page():
        """Opening the link confirms nothing (a mail scanner opens links on its own): a button."""
        token = request.args.get("t", "")
        uid = mail.link_owner(token)
        if not uid:
            return _dead_link()
        with lang.using(lang.for_user(uid)):
            form = ('<form method="post" action="/api/notify/email/confirm" style="margin-top:24px">'
                    f'<input type="hidden" name="t" value="{html.escape(token, quote=True)}">'
                    '<button type="submit" style="font-size:18px;padding:12px 32px;border-radius:12px;'
                    f'border:0;background:#007aff;color:#fff">{html.escape(lang.say("mail_confirm_button"))}'
                    '</button></form>')
            return _page(lang.say("mail_confirm_page"), 200, form)

    @app.route("/api/notify/email/confirm", methods=["POST"])
    def api_notify_email_confirm():
        uid = mail.confirm(request.form.get("t", ""))
        if not uid:
            return _dead_link()
        with lang.using(lang.for_user(uid)):
            return _page(lang.say("mail_confirmed_page"), 200)
