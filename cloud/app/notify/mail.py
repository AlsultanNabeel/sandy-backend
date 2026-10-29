"""The email channel: what a task found, to the user's own address once he confirmed it.

He gives the address in the app (`ask_to_confirm`, at most LINKS_A_DAY links a day); a link
goes to it, and opening it shows a page with a «Confirm» button (`link_owner` reads it and uses
nothing, since a mail scanner opens links on its own); until he presses it (`confirm`) no result
is emailed, and what was found before is never sent later. Then each task's results go as he
said (`tasks.how`): right away, a summary once a day at his hour, or at most once every N hours
(once an hour when he said nothing). What is not due yet is held and goes in its next email,
with the next result or when the minute runner hands the channels what they hold (`flush`).
An account gets at most ACCOUNT_CAP emails an hour; the last of them gathers every result that
was due, and the rest wait for the hour. A send that fails keeps it held for the next. The
words around a result are in his saved language.

How it leaves is the settings, never the code: any SMTP server. Gmail with an app password
now; a sending service on our own domain later is the same settings with other values.
  SANDY_SMTP_HOST      smtp.gmail.com by default
  SANDY_SMTP_PORT      587 (STARTTLS) by default; 465 is TLS from the start
  SANDY_SMTP_USER      the account it signs in as
  SANDY_SMTP_PASSWORD  its app password
  SANDY_EMAIL_FROM     who it is from (the user above by default)
  SANDY_PUBLIC_URL     this server's address, for the confirmation link
Without the user, the password or the address, or with one still a placeholder (CHANGE_ME),
nothing is asked or sent.
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

from app.blocks import _base, tasks
from app.brain import lang
from app.features import users_store

logger = logging.getLogger(__name__)

# At most this many emails an hour to one account; the last one gathers the rest.
ACCOUNT_CAP = 20
HOUR = timedelta(hours=1)
LINK_LIVES = timedelta(hours=24)
# A second link inside this is not sent: the same address waits, another is refused.
RESEND_AFTER = timedelta(minutes=5)
# At most this many links to one account in LINKS_WINDOW, whatever the address.
LINKS_A_DAY = 5
LINKS_WINDOW = timedelta(hours=24)
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


# A value left to fill by hand on the dashboard is no value: nothing is asked or sent with it.
_PLACEHOLDERS = frozenset({"change_me", "changeme", "todo", "xxx"})


def ready() -> bool:
    return all(_setting(n) and _setting(n).lower() not in _PLACEHOLDERS
               for n in ("SANDY_SMTP_USER", "SANDY_SMTP_PASSWORD", "SANDY_PUBLIC_URL"))


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
    to do). ValueError `bad_address` / `too_soon` / `too_many` (LINKS_A_DAY reached),
    RuntimeError `not_set_up`, OSError when the link did not leave."""
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
    if users_store.notify_links_since(user_id, _now() - LINKS_WINDOW) >= LINKS_A_DAY:
        raise ValueError("too_many")
    token = secrets.token_urlsafe(32)
    link = f"{_setting('SANDY_PUBLIC_URL').rstrip('/')}/api/notify/email/confirm?t={token}"
    with lang.using(lang.for_user(user_id)):
        _post(address, lang.say("mail_confirm_subject"), lang.say("mail_confirm_body", link=link))
    users_store.set_notify_email(user_id, {"address": address, "confirmed": False,
                                           "token": _hash(token), "asked_at": _now()})
    users_store.note_notify_link(user_id, _now(), _now() - LINKS_WINDOW)
    return "sent"


def link_owner(token: str) -> Optional[str]:
    """The account whose live link this is; None for a wrong, used or old one. Reads only."""
    uid = users_store.user_by_notify_token(_hash(str(token or "")))
    if not uid:
        return None
    asked = _aware(users_store.get_notify_email(uid).get("asked_at"))
    return uid if asked and _now() - asked <= LINK_LIVES else None


def confirm(token: str) -> Optional[str]:
    """The account the link confirmed, once (its button, never the opening); None for a wrong,
    used or old one."""
    uid = link_owner(token)
    if not uid:
        return None
    saved = users_store.get_notify_email(uid)
    users_store.set_notify_email(uid, {"address": saved["address"], "confirmed": True})
    return uid


def forget(user_id: str) -> None:
    users_store.set_notify_email(user_id, None)


def _address(user_id: str) -> str:
    saved = users_store.get_notify_email(user_id)
    return saved.get("address", "") if saved.get("confirmed") else ""


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())[:120]


def _subject(rows: List[Dict[str, Any]]) -> str:
    """What is new, from the newest result's first line, and how many more came with it."""
    newest = str(rows[-1].get("body") or rows[-1].get("title") or "").strip().splitlines() or [""]
    line = _one_line(newest[0])[:90]
    if len(rows) == 1:
        return lang.say("mail_result_subject", line=line)
    return lang.say("mail_results_subject", line=line, n=len(rows) - 1)


def _block(row: Dict[str, Any], titled: bool) -> str:
    """One result: what changed, when (his clock), and how things are now."""
    from app.brain.when import local_text
    lines = [f"«{_one_line(row.get('title'))}»"] if titled else []
    lines.append(str(row.get("body") or "").strip())
    lines.append(lang.say("mail_at", time=local_text(row.get("at"))))
    if row.get("state"):
        lines.append(lang.say("mail_now", state=row["state"]))
    return "\n".join(lines)


def _rtl(text: str) -> str:
    """Arabic reads right to left in a plain-text email too: each line starts with the mark."""
    if lang.current() != lang.AR:
        return text
    return "\n".join(f"\u200f{ln}" if ln.strip() else ln for ln in text.splitlines())


def _compose(rows: List[Dict[str, Any]]) -> tuple:
    titled = len({_one_line(r.get("title")) for r in rows}) > 1
    body = "\n\n———\n\n".join(_block(r, titled) for r in rows)
    return _subject(rows), _rtl(f"{body}\n\n—\n{lang.say('mail_footer')}")


def _last_slot(at: str, now: datetime) -> datetime:
    """The latest «at» on his clock that is not after now."""
    from app.utils.time import USER_TZ
    hour, minute = (int(x) for x in at.split(":"))
    local = now.astimezone(USER_TZ)
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=1)
    return slot.astimezone(timezone.utc)


def _due(coll, task_id: str, now: datetime) -> bool:
    """Whether this task's held results may go now, the way he said."""
    way = tasks.how(tasks.get(task_id) or {})
    if way["mode"] == tasks.INSTANT:
        return True
    if way["mode"] == tasks.DAILY:
        # Its summary goes at his hour with what was held before it; what came after waits.
        first = list(coll.find({"task_id": task_id, "email": HELD}).sort("held_at", 1).limit(1))
        return bool(first) and _aware(first[0].get("held_at") or first[0]["at"]) <= _last_slot(
            way["at"], now)
    last = list(coll.find({"task_id": task_id, "email": SENT}).sort("emailed_at", -1).limit(1))
    return not last or now - _aware(last[0]["emailed_at"]) >= way["hours"] * HOUR


def _sent_this_hour(coll, now: datetime) -> int:
    return len(coll.distinct("email_id", {"email": SENT, "emailed_at": {"$gt": now - HOUR}}))


def _email(coll, address: str, uid: str, rows: List[Dict[str, Any]]) -> None:
    with lang.using(lang.for_user(uid)):
        subject, body = _compose(rows)
    _post(address, subject, body)
    coll.update_many({"_id": {"$in": [r["_id"] for r in rows]}},
                     {"$set": {"email": SENT, "emailed_at": _now(), "email_id": _base.new_id()}})


def send(row: Dict[str, Any]) -> None:
    """The channel (`notify.CHANNELS`): hold the result, then send what may go now. Nothing for
    an address not confirmed."""
    from app import notify
    from app.utils.user_profiles import current_user_id

    coll = _base.coll(notify.RESULTS)
    if coll is None or not ready() or not _address(current_user_id() or ""):
        return
    coll.update_one({"_id": row["id"]}, {"$set": {"email": HELD, "held_at": _now()}})
    flush()


def flush() -> None:
    """The current user's held results that may go now, each task the way he said, at most
    ACCOUNT_CAP emails an hour: the last one gathers every result that was due."""
    from app import notify
    from app.utils.user_profiles import current_user_id

    uid, coll = current_user_id() or "", _base.coll(notify.RESULTS)
    address = _address(uid) if coll is not None and ready() else ""
    if not address:
        return
    now = _now()
    held: Dict[str, List[Dict[str, Any]]] = {}
    for r in coll.find({"email": HELD}).sort("at", 1):
        held.setdefault(str(r.get("task_id") or ""), []).append(r)
    due = [t for t in held if _due(coll, t, now)]
    for n, task_id in enumerate(due):
        sent = _sent_this_hour(coll, now)
        if sent >= ACCOUNT_CAP:
            return
        if sent == ACCOUNT_CAP - 1 and n < len(due) - 1:
            _email(coll, address, uid, [r for t in due[n:] for r in held[t]])
            return
        _email(coll, address, uid, held[task_id])
