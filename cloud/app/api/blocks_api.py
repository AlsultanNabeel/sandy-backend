"""REST over the three blocks and the kinds table (rebuild phase 3; §2.9, §2.12).

  GET/POST /api/entries     PATCH/DELETE /api/entries/<id>     the log
  GET/POST /api/items       PATCH/DELETE /api/items/<id>       the lists
  GET/POST /api/schedules   PATCH/DELETE /api/schedules/<id>   anything that fires
  GET  /api/kinds           the kinds table, so the app builds its screens from it
  POST /api/summary         {period, focus?} -> {text}
  GET  /api/stats           My Life's numbers: entries per day (30), this month's totals
  POST /api/budget          {amount}: the monthly spending limit (0 removes it)

A POST may carry its own ``id`` (32 hex): the app makes rows offline and sends them
later, so the id it already uses must stay, and a resent POST must not double the row.

Every route runs in the caller's tenant (`require_tenant`); the block stores'
tenant-scoped handles do the isolation. A bad input is 400 with error + message.
"""

from __future__ import annotations

import functools
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from flask import jsonify, request
from pymongo.errors import DuplicateKeyError

from app.utils.ltm_crypto import decrypt_field, encrypt_field
from app.api.auth_handlers import require_auth, require_tenant
from app.api.metering import meter_claims
from app.blocks import _base, entries, habits, items, schedules
from app.blocks.kinds import KINDS, LIST, LOG, SCHEDULE, KindError, get_kind
from app.brain import summary
from app.brain.categorize import categorize_later
from app.brain import when as W
from app.features import users_store
from app.utils.user_profiles import current_user_id

MAX_TEXT_CHARS = 2000
MAX_DATA_CHARS = 8000
DEFAULT_LIMIT = 100
# The runner owns sent/failed; the app may only re-arm or cancel.
APP_STATUSES = ("pending", "cancelled")

_MESSAGES = {
    "invalid_body": "الطلب مش مفهوم.",
    "text_required": "اكتب النص أول.",
    "text_too_long": "النص طويل كثير.",
    "data_too_big": "المعلومات الإضافية كبيرة كثير.",
    "invalid_kind": "النوع أو الحقول مش معروفة.",
    "invalid_date": "التاريخ مش مفهوم.",
    "invalid_limit": "العدد مش صحيح.",
    "invalid_cursor": "الصفحة المطلوبة مش مفهومة.",
    "invalid_done": "قيمة «تم» لازم تكون صح أو غلط.",
    "fire_at_required": "حدّد وقت التذكير.",
    "fire_at_in_past": "الوقت لازم يكون بالمستقبل.",
    "invalid_recurrence": "التكرار مش مفهوم.",
    "invalid_status": "الحالة مش مسموحة.",
    "invalid_period": "الفترة مش معروفة.",
    "not_found": "ما لقيته.",
    "not_saved": "ما قدرت أحفظ، جرّب كمان شوي.",
    "invalid_id": "رقم التعريف مش صحيح.",
    "invalid_amount": "المبلغ مش صحيح.",
    "id_taken": "رقم التعريف مستعمل.",
    "summary_failed": "ما قدرت أعمل الملخّص هلّق، جرّب كمان شوي.",
}

_TYPE_NAMES = {str: "string", int: "int", float: "number", bool: "bool",
               list: "list", dict: "object", datetime: "datetime"}


class _Invalid(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _refuse(code: str, status: int = 400):
    return jsonify({"error": code, "message": _MESSAGES.get(code, _MESSAGES["invalid_body"])}), status


def _answers_invalid(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except _Invalid as exc:
            return _refuse(exc.code, exc.status)
        except KindError:
            return _refuse("invalid_kind")
        except DuplicateKeyError:
            return _refuse("id_taken", 409)
    return wrapped


# ── input ────────────────────────────────────────────────────────────────────

def _body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise _Invalid("invalid_body")
    return body


def _text(value: Any, *, required: bool) -> Optional[str]:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise _Invalid("text_required")
    if len(value) > MAX_TEXT_CHARS:
        raise _Invalid("text_too_long")
    return value.strip()


_CLIENT_ID = re.compile(r"^[0-9a-f]{32}$")


def _client_id(body: Mapping[str, Any]) -> Optional[str]:
    """The app's own id for a new row, or None to let the store make one."""
    value = body.get("id")
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _CLIENT_ID.match(value):
        raise _Invalid("invalid_id")
    return value


def _new_text(body: Mapping[str, Any]) -> Optional[str]:
    """A PATCH's text: absent leaves it, present must not be empty."""
    return _text(body["text"], required=True) if "text" in body else None


def _when(value: Any, *, end: bool = False) -> Optional[datetime]:
    """ISO date/datetime; naive counts as the user's zone. ``end``: a bare date covers its day."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise _Invalid("invalid_date")
    dt = W.parse_bound(value, end=end)
    if dt is None:
        raise _Invalid("invalid_date")
    return dt


def _data(block: str, name: str, value: Any) -> Optional[Dict[str, Any]]:
    """The kind's ``data``, with its datetime fields read from ISO strings."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _Invalid("invalid_kind")
    if len(json.dumps(value, ensure_ascii=False, default=str)) > MAX_DATA_CHARS:
        raise _Invalid("data_too_big")
    row = get_kind(block, name)
    if row is None:
        raise _Invalid("invalid_kind")
    out = dict(value)
    for key, typ in row.fields.items():
        if typ is datetime and isinstance(out.get(key), str):
            out[key] = _when(out[key])
    return out


def _limit() -> int:
    raw = request.args.get("limit", "")
    if not raw:
        return DEFAULT_LIMIT
    try:
        n = int(raw)
    except ValueError:
        raise _Invalid("invalid_limit") from None
    if n < 1:
        raise _Invalid("invalid_limit")
    return n


def _iso_utc(value: Any) -> str:
    """A row's time as UTC ISO (the store hands back naive UTC)."""
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _cursor(raw: Optional[str]):
    """`next` from the page before → ``(created_at, id)``; a malformed one is a 400."""
    if not raw:
        return None
    at, sep, row_id = str(raw).partition("|")
    try:
        when = datetime.fromisoformat(at)
    except ValueError:
        raise _Invalid("invalid_cursor") from None
    if not sep or not row_id:
        raise _Invalid("invalid_cursor")
    return when, row_id


def _flag(value: Any) -> Optional[bool]:
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise _Invalid("invalid_done")


# ── output ───────────────────────────────────────────────────────────────────

def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return W.iso(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _shown(row: Optional[Mapping[str, Any]], extra_key: str) -> Optional[Dict[str, Any]]:
    """JSON-ready row; an encrypted text (``<extra_key>.encrypted``) is decrypted for its owner."""
    if row is None:
        return None
    out = _plain(dict(row))
    if (row.get(extra_key) or {}).get("encrypted"):
        out["text"] = decrypt_field(row.get("text", ""))
    return out


def _sealed(text: str) -> tuple:
    """(stored text, encrypted?) — plaintext when no key is configured."""
    sealed = encrypt_field(text)
    return sealed, sealed != text


def _saved(new_id: str, getter, extra_key: str):
    if not new_id:
        raise _Invalid("not_saved", 503)
    return jsonify({"ok": True, "id": new_id, "item": _shown(getter(new_id), extra_key)}), 200


def _found(ok: bool, row_id: str, getter, extra_key: str):
    if not ok:
        raise _Invalid("not_found", 404)
    return jsonify({"ok": True, "item": _shown(getter(row_id), extra_key)}), 200


# ── routes ───────────────────────────────────────────────────────────────────

def _kind_row(k) -> Dict[str, Any]:
    return {"name": k.name, "block": k.block, "labels": {"ar": k.ar, "en": k.en},
            "icon": k.icon, "prefix": k.name.endswith(":"),
            "fields": {f: _TYPE_NAMES.get(t, "string") for f, t in k.fields.items()}}


def register_blocks_api(app, mongo_db=None):
    # The block stores read the app's own handle (app.db); mongo_db is kept for the
    # same registration signature as the other modules.
    del mongo_db

    @app.route("/api/kinds", methods=["GET"])
    @require_auth
    def api_kinds(claims):
        return jsonify({"kinds": [_kind_row(k) for k in KINDS]}), 200

    # ── entries (log) ────────────────────────────────────────────────────────
    @app.route("/api/entries", methods=["GET"])
    @require_tenant
    @_answers_invalid
    def api_entries_list(claims):
        rows = entries.list_entries(request.args.get("kind") or None,
                                    since=_when(request.args.get("since")),
                                    until=_when(request.args.get("until"), end=True),
                                    text=request.args.get("q", "")[:MAX_TEXT_CHARS],
                                    # Chat summaries are Sandy's memory, most of the log by
                                    # count; the user's log shows them only when asked by kind.
                                    exclude=("summary",),
                                    limit=_limit())
        return jsonify({"items": [_shown(r, "data") for r in rows]}), 200

    @app.route("/api/entries", methods=["POST"])
    @require_tenant
    @_answers_invalid
    def api_entries_add(claims):
        body = _body()
        cid = _client_id(body)
        if cid and entries.get(cid):
            return _saved(cid, entries.get, "data")  # sent twice: already here
        kind = str(body.get("kind") or "")
        text = _text(body.get("text"), required=True)
        data = _data(LOG, kind, body.get("data"))
        new_id = entries.add(kind, text, data, at=_when(body.get("at")), source="app", doc_id=cid)
        categorize_later(new_id, kind, text, data)
        return _saved(new_id, entries.get, "data")

    @app.route("/api/stats", methods=["GET"])
    @require_tenant
    @_answers_invalid
    def api_stats(claims):
        """My Life's numbers over the whole log (not the newest page the app holds)."""
        out = entries.stats()
        out["budget"] = users_store.get_budget(current_user_id())
        out["habit_progress"] = habits.progress()
        return jsonify(out), 200

    @app.route("/api/budget", methods=["POST"])
    @require_tenant
    @_answers_invalid
    def api_budget(claims):
        """{amount}: the monthly spending limit; 0 removes it."""
        amount = _body().get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
            raise _Invalid("invalid_amount")
        if not users_store.set_budget(current_user_id(), float(amount)):
            raise _Invalid("not_saved", 503)
        return jsonify({"ok": True, "budget": float(amount)}), 200

    @app.route("/api/entries/<entry_id>", methods=["PATCH"])
    @require_tenant
    @_answers_invalid
    def api_entries_update(claims, entry_id):
        body = _body()
        current = entries.get(entry_id)
        if current is None:
            raise _Invalid("not_found", 404)
        text, embed = _new_text(body), True
        if text is not None and (current.get("data") or {}).get("encrypted"):
            # Re-seal it, and never embed what is kept encrypted.
            text, embed = _sealed(text)[0], False
        data = _data(LOG, current["kind"], body.get("data"))
        ok = entries.update(entry_id, text=text, data=data, at=_when(body.get("at")), embed=embed)
        if data is not None:
            categorize_later(entry_id, current["kind"], text or current.get("text") or "", data)
        return _found(ok, entry_id, entries.get, "data")

    @app.route("/api/entries/<entry_id>", methods=["DELETE"])
    @require_tenant
    @_answers_invalid
    def api_entries_delete(claims, entry_id):
        return _found(entries.delete(entry_id), entry_id, lambda _i: None, "data")

    # ── items (lists) ────────────────────────────────────────────────────────
    @app.route("/api/items", methods=["GET"])
    @require_tenant
    @_answers_invalid
    def api_items_list(claims):
        """A page of rows: an open list oldest first, the done half newest first. `next` is
        there when more follow; pass it back as `cursor`."""
        done = _flag(request.args.get("done"))
        order = "newest" if done else "created"
        limit = _limit()
        rows = items.list_items(request.args.get("list") or None, done=done,
                                text=request.args.get("q", "")[:MAX_TEXT_CHARS],
                                order=order, limit=limit, paged=True,
                                after=_cursor(request.args.get("cursor")))
        out: Dict[str, Any] = {"items": [_shown(r, "data") for r in rows]}
        if len(rows) == min(limit, _base.MAX_LIMIT):
            last = rows[-1]
            out["next"] = f"{_iso_utc(last.get('created_at'))}|{last['id']}"
        return jsonify(out), 200

    @app.route("/api/items/lists", methods=["GET"])
    @require_tenant
    @_answers_invalid
    def api_items_lists(claims):
        """Every list the user has rows in (a list's name is not on its first page)."""
        return jsonify({"lists": items.list_names()}), 200

    @app.route("/api/items", methods=["POST"])
    @require_tenant
    @_answers_invalid
    def api_items_add(claims):
        body = _body()
        cid = _client_id(body)
        if cid and items.get(cid):
            return _saved(cid, items.get, "data")
        name = str(body.get("list") or "")
        text = _text(body.get("text"), required=True)
        new_id = items.add(name, text, _data(LIST, name, body.get("data")),
                           done=bool(_flag(body.get("done"))), due=_when(body.get("due")),
                           priority=_text(body.get("priority"), required=False) or "",
                           doc_id=cid)
        return _saved(new_id, items.get, "data")

    @app.route("/api/items/<item_id>", methods=["PATCH"])
    @require_tenant
    @_answers_invalid
    def api_items_update(claims, item_id):
        body = _body()
        current = items.get(item_id)
        if current is None:
            raise _Invalid("not_found", 404)
        extra: Dict[str, Any] = {}
        if "due" in body:
            extra["due"] = _when(body["due"])  # null clears it
        ok = items.update(item_id, text=_new_text(body),
                          done=_flag(body.get("done")),
                          priority=_text(body.get("priority"), required=False),
                          data=_data(LIST, current["list"], body.get("data")), **extra)
        return _found(ok, item_id, items.get, "data")

    @app.route("/api/items/<item_id>", methods=["DELETE"])
    @require_tenant
    @_answers_invalid
    def api_items_delete(claims, item_id):
        return _found(items.delete(item_id), item_id, lambda _i: None, "data")

    # ── schedules ────────────────────────────────────────────────────────────
    def _rule(value: Any) -> Optional[str]:
        if value is None:
            return None
        rule = W.recurrence_rule(value if isinstance(value, str) else "?")
        if rule is None:
            raise _Invalid("invalid_recurrence")
        return rule

    def _future(value: Any) -> datetime:
        if value in (None, ""):
            raise _Invalid("fire_at_required")
        fire_at = _when(value)
        if fire_at <= datetime.now(timezone.utc):
            raise _Invalid("fire_at_in_past")
        return fire_at

    @app.route("/api/schedules", methods=["GET"])
    @require_tenant
    @_answers_invalid
    def api_schedules_list(claims):
        status = request.args.get("status") or None
        if status is not None and status not in schedules.STATUSES:
            raise _Invalid("invalid_status")
        rows = schedules.list_schedules(request.args.get("kind") or None, status=status,
                                        since=_when(request.args.get("from")),
                                        until=_when(request.args.get("to"), end=True),
                                        limit=_limit())
        return jsonify({"items": [_shown(r, "payload") for r in rows]}), 200

    @app.route("/api/schedules", methods=["POST"])
    @require_tenant
    @_answers_invalid
    def api_schedules_add(claims):
        body = _body()
        cid = _client_id(body)
        if cid and schedules.get(cid):
            return _saved(cid, schedules.get, "payload")
        kind = str(body.get("kind") or "")
        text = _text(body.get("text"), required=True)
        payload = _data(SCHEDULE, kind, body.get("payload")) or {}
        fire_at = _future(body.get("fire_at"))
        rule = _rule(body.get("recurrence")) or ""
        if kind == "message_to_future_self":
            # Sealed at rest: only its owner reads it back.
            text, payload["encrypted"] = _sealed(text)
        new_id = schedules.add(kind, text, fire_at, payload, recurrence=rule, doc_id=cid)
        return _saved(new_id, schedules.get, "payload")

    @app.route("/api/schedules/<schedule_id>", methods=["PATCH"])
    @require_tenant
    @_answers_invalid
    def api_schedules_update(claims, schedule_id):
        body = _body()
        current = schedules.get(schedule_id)
        if current is None:
            raise _Invalid("not_found", 404)
        status = body.get("status")
        if status is not None and status not in APP_STATUSES:
            raise _Invalid("invalid_status")
        text = _new_text(body)
        payload = _data(SCHEDULE, current["kind"], body.get("payload"))
        was_sealed = (current.get("payload") or {}).get("encrypted")
        if payload is not None and was_sealed:
            payload.setdefault("encrypted", True)
        if text is not None and was_sealed:
            text = _sealed(text)[0]
        fire_at = _future(body["fire_at"]) if "fire_at" in body else None
        ok = schedules.update(schedule_id, text=text, fire_at=fire_at,
                              recurrence=_rule(body.get("recurrence")),
                              payload=payload, status=status)
        return _found(ok, schedule_id, schedules.get, "payload")

    @app.route("/api/schedules/<schedule_id>", methods=["DELETE"])
    @require_tenant
    @_answers_invalid
    def api_schedules_delete(claims, schedule_id):
        return _found(schedules.delete(schedule_id), schedule_id, lambda _i: None, "payload")

    # ── summary ──────────────────────────────────────────────────────────────
    @app.route("/api/summary", methods=["POST"])
    @require_tenant
    @_answers_invalid
    def api_summary(claims):
        body = _body()
        period = str(body.get("period") or "")
        if period not in W.PERIODS:
            raise _Invalid("invalid_period")
        focus = _text(body.get("focus"), required=False) or ""
        refusal = meter_claims(claims)
        if refusal:
            return jsonify(refusal[0]), refusal[1]
        result = summary.summarize_text(str(current_user_id() or ""), period, focus)
        if not result["ok"]:
            raise _Invalid("summary_failed", 503)
        return jsonify({"ok": True, "text": result["text"], "count": result["count"]}), 200
