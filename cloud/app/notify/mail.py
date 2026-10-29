"""The email channel: what a task found, to the user's own address once he confirmed it.

He gives the address in the app (`ask_to_confirm`); a link goes to it, and until he opens it
(`confirm`) no result is emailed, and what was found before is never sent later. Then one email
per task an hour at most (`EVERY`): what comes inside the hour is held and goes in the next
one, with the next result or on the task's next run after the hour (`flush`). A send that
fails keeps it held for the next. The words around a result are in his saved language.

How it leaves is the settings, never the code: any SMTP server. Gmail with an app password
now; a sending service on our own domain later is the same settings with other values.
  SANDY_SMTP_HOST      smtp.gmail.com by default
  SANDY_SMTP_PORT      587 (STARTTLS) by default; 465 is TLS from the start
  SANDY_SMTP_USER      the account it signs in as
  SANDY_SMTP_PASSWORD  its app password
  SANDY_EMAIL_FROM     who it is from (the user above by default)
  SANDY_PUBLIC_URL     this server's address, for the confirmation link
Without the user, the password or the address nothing is asked or sent.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from app.blocks import _base
from app.brain import lang
from app.features import users_store

logger = logging.getLogger(__name__)

EVERY = timedelta(hours=1)
LINK_LIVES = timedelta(hours=24)
# A second link inside this is not sent: the same address waits, another is refused.
RESEND_AFTER = timedelta(minutes=5)
TIMEOUT_S = 15
HELD, SENT = "held", "sent"
_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(at: Optional[datetime]) -> Optional[datetime]:
    if at is None:
        return None
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


def ready() -> bool:
    return all(_setting(n) for n in ("SANDY_SMTP_USER", "SANDY_SMTP_PASSWORD", "SANDY_PUBLIC_URL"))


def _post(to: str, subject: str, body: str) -> None:
    """One email out; an OSError (smtplib's errors are) when it did not leave."""
    user = _setting("SANDY_SMTP_USER")
    msg = EmailMessage()
    msg["From"] = _setting("SANDY_EMAIL_FROM", user)
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host, port = _setting("SANDY_SMTP_HOST", "smtp.gmail.com"), int(_setting("SANDY_SMTP_PORT", "587"))
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_S, context=context) as server:
            server.login(user, _setting("SANDY_SMTP_PASSWORD"))
            server.send_message(msg)
        return
    with smtplib.SMTP(host, port, timeout=TIMEOUT_S) as server:
        server.starttls(context=context)
        server.login(user, _setting("SANDY_SMTP_PASSWORD"))
        server.send_message(msg)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(address: str) -> str:
    address = str(address or "").strip().lower()
    if len(address) > 254 or not _ADDRESS.match(address):
        raise ValueError("bad_address")
    return address


def status(user_id: str) -> Dict[str, Any]:
    saved = users_store.get_notify_email(user_id)
    return {"address": saved.get("address", ""), "confirmed": bool(saved.get("confirmed")),
            "ready": ready()}


def ask_to_confirm(user_id: str, address: str) -> str:
    """Send the link: "sent", "pending" (one went to it a moment ago) or "confirmed" (nothing
    to do). ValueError `bad_address` / `too_soon`, RuntimeError `not_set_up`, OSError when the
    link did not leave."""
    address = _clean(address)
    if not ready():
        raise RuntimeError("not_set_up")
    saved = users_store.get_notify_email(user_id)
    same = saved.get("address") == address
    if same and saved.get("confirmed"):
        return "confirmed"
    asked = _aware(saved.get("asked_at"))
    if asked and not saved.get("confirmed") and _now() - asked < RESEND_AFTER:
        if same:
            return "pending"
        raise ValueError("too_soon")
    token = secrets.token_urlsafe(32)
    link = f"{_setting('SANDY_PUBLIC_URL').rstrip('/')}/api/notify/email/confirm?t={token}"
    with lang.using(lang.for_user(user_id)):
        _post(address, lang.say("mail_confirm_subject"), lang.say("mail_confirm_body", link=link))
    users_store.set_notify_email(user_id, {"address": address, "confirmed": False,
                                           "token": _hash(token), "asked_at": _now()})
    return "sent"


def confirm(token: str) -> Optional[str]:
    """The account the link confirmed, once; None for a wrong, used or old one."""
    uid = users_store.user_by_notify_token(_hash(str(token or "")))
    if not uid:
        return None
    saved = users_store.get_notify_email(uid)
    asked = _aware(saved.get("asked_at"))
    if not asked or _now() - asked > LINK_LIVES:
        return None
    users_store.set_notify_email(uid, {"address": saved["address"], "confirmed": True})
    return uid


def forget(user_id: str) -> None:
    users_store.set_notify_email(user_id, None)


def _address(user_id: str) -> str:
    saved = users_store.get_notify_email(user_id)
    return saved.get("address", "") if saved.get("confirmed") else ""


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())[:120]


def _compose(rows: List[Dict[str, Any]]) -> tuple:
    title = _one_line(rows[-1].get("title"))
    if len(rows) == 1:
        subject = lang.say("mail_result_subject", title=title)
    else:
        subject = lang.say("mail_results_subject", n=len(rows), title=title)
    body = "\n\n———\n\n".join(str(r.get("body") or "") for r in rows)
    return subject, f"{body}\n\n—\n{lang.say('mail_footer')}"


def _send_held(task_id: str) -> None:
    from app import notify
    from app.utils.user_profiles import current_user_id

    uid, coll = current_user_id(), _base.coll(notify.RESULTS)
    address = _address(uid or "") if coll is not None and ready() else ""
    if not address:
        return
    last = list(coll.find({"task_id": task_id, "email": SENT}).sort("emailed_at", -1).limit(1))
    if last and _now() - _aware(last[0]["emailed_at"]) < EVERY:
        return
    held = list(coll.find({"task_id": task_id, "email": HELD}).sort("at", 1))
    if not held:
        return
    with lang.using(lang.for_user(uid)):
        subject, body = _compose(held)
    _post(address, subject, body)
    coll.update_many({"_id": {"$in": [r["_id"] for r in held]}},
                     {"$set": {"email": SENT, "emailed_at": _now()}})


def send(row: Dict[str, Any]) -> None:
    """The channel (`notify.CHANNELS`): hold the result, then send what is held if its hour
    allows. Nothing for an address not confirmed."""
    from app import notify
    from app.utils.user_profiles import current_user_id

    coll = _base.coll(notify.RESULTS)
    if coll is None or not ready() or not _address(current_user_id() or ""):
        return
    coll.update_one({"_id": row["id"]}, {"$set": {"email": HELD}})
    _send_held(str(row.get("task_id") or ""))


def flush(task_id: str) -> None:
    """On a task's run: what it held goes once its hour has passed."""
    _send_held(str(task_id))
