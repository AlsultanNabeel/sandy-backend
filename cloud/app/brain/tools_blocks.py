"""The tools that read and write the three blocks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.brain.categorize import categorize_later
from app.utils.ltm_crypto import decrypt_field, encrypt_field
from app.utils.time import USER_TZ
from app.blocks import _base, entries, items, schedules
from app.blocks.kinds import LIST, LOG, SCHEDULE, KindError, by_alias, get_kind, names
from app.brain import when as W
from app.brain.ctx import TurnCtx, needs_confirmation, refused
from app.brain.matching import match_rows
from app.brain.matching import match_key

MAX_ROWS = 30
SUMMARY_ROWS = 200
# The moods strong enough to keep as an emotional moment.
SIGNIFICANT_MOODS = ("stressed", "frustrated", "sad", "angry", "happy", "excited")


# ── row shapes the model sees ────────────────────────────────────────────────

def _entry_row(e: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(e.get("data") or {})
    text = e.get("text", "")
    if data.pop("encrypted", False):
        text = decrypt_field(text)
    return {"id": e["id"], "kind": e.get("kind"), "text": text,
            "at": W.iso(e.get("at")), **({"data": data} if data else {})}


def _item_row(i: Dict[str, Any]) -> Dict[str, Any]:
    row = {"id": i["id"], "list": i.get("list"), "text": i.get("text", ""),
           "done": bool(i.get("done"))}
    if i.get("due"):
        row["due"] = W.iso(i["due"])
    if i.get("priority"):
        row["priority"] = i["priority"]
    return row


# The schedules that are the user's own; nudges and scene timers are the app's.
USER_SCHEDULES = ("reminder", "message_to_future_self")


def _schedule_row(s: Dict[str, Any]) -> Dict[str, Any]:
    # A message to his future self stays sealed until it is delivered.
    sealed = s.get("kind") == "message_to_future_self" and s.get("status") != "sent"
    row = {"id": s["id"], "kind": s.get("kind"),
           "text": "(رسالة مختومة لحد موعدها)" if sealed else decrypt_field(s.get("text", "")),
           "when": W.iso(s.get("fire_at")), "status": s.get("status")}
    if s.get("recurrence"):
        row["recurrence"] = s["recurrence"]
    return row


def _matches_query(row: Dict[str, Any], query: str) -> bool:
    words = [w for w in match_key(query).split() if len(w) >= 2]
    if not words:
        return True
    hay = match_key(" ".join(str(v) for v in row.values()))
    return any(w in hay for w in words)


def _list_name(args: Dict[str, Any]) -> str:
    name = str(args.get("list") or "").strip()
    project = str(args.get("project") or "").strip()
    return f"project:{project}" if name == "project" and project else name


# ── remember / recall / summarize ────────────────────────────────────────────

def _mood(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """An emotional moment as a `mood` entry: a significant mood, the user's
    words (200 chars) encrypted and never embedded, at most once per turn."""
    mood = str((args.get("data") or {}).get("mood") or "")
    if mood not in SIGNIFICANT_MOODS:
        return refused(f"data.mood must be one of {SIGNIFICANT_MOODS}")
    if ctx.artifacts.get("mood_saved"):
        return {"ok": True, "id": ctx.artifacts["mood_saved"]}
    words = (ctx.message or str(args.get("text") or "")).strip()[:200]
    sealed = encrypt_field(words)
    eid = entries.add("mood", sealed, {"mood": mood, "encrypted": sealed != words},
                      source=ctx.source, embed=False)
    ctx.artifacts["mood_saved"] = eid
    return {"ok": bool(eid), "id": eid} if eid else refused("not saved")


def remember(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    kind, text = str(args.get("kind") or "note"), str(args.get("text") or "").strip()
    if not text:
        return refused("text is empty")
    if kind == "mood":
        return _mood(args, ctx)
    try:
        eid = entries.add(kind, text, args.get("data") or None, source=ctx.source)
    except KindError as exc:
        return refused(str(exc))
    if not eid:
        return refused("not saved")
    out = {"ok": True, "id": eid, "reply": f"سجّلتها ✅ «{text}»"}
    categorize_later(eid, kind, text, args.get("data"))
    if kind == "expense":
        note = budget_note(ctx.user_id)
        if note:
            out["budget"] = note
    return out


def budget_note(user_id: str) -> str:
    """A line for the model once this month's spending passes 80% of the limit, else ""."""
    from app.features import users_store

    budget = users_store.get_budget(user_id)
    if not budget:
        return ""
    spent = entries.stats(days=1)["spent"]
    if spent < budget * 0.8:
        return ""
    state = "تعدّى ميزانية الشهر" if spent >= budget else "قرّب يخلّص ميزانية الشهر"
    return f"{state}: صرف {spent:g} من {budget:g}. نبّهيه بلطف."


def undo_last(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«لا، احذفيه» / «غلط» right after she did something: what her previous reply added
    goes, what it changed or deleted comes back. Devices are not undone."""
    from app.blocks import _base
    from app.brain import stm

    effects = stm.take_last_effects(ctx.thread_id or ctx.user_id, ctx.user_id)
    if not effects:
        return refused("nothing to undo: the last reply changed nothing in the lists, log or reminders")
    undone = _base.undo(effects)
    names = [decrypt_field(e["text"]) for e in effects if e.get("text")]
    return {"ok": bool(undone), "undone": undone, "items": names,
            "reply": "رجّعت عنه ✅ " + "، ".join(f"«{n}»" for n in names[:3])}


def log_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«لا قصدي أربعين مش خمسين»، «احذفي هالمصروف»، «نقلت بيت جديد»، «انسي إني بحب القهوة»:
    a log row is changed or deleted, not logged again. With no id and no text, the newest
    row of the kind. Encrypted rows are sealed again and never embedded."""
    kind = str(args.get("kind") or "").strip() or None
    pool = [_entry_row(e) for e in entries.list_entries(kind, exclude=("summary",), limit=MAX_ROWS * 2)]
    if args.get("id") or args.get("match_text"):
        picked = _pick(args, pool, lambda i: _entry_row(e) if (e := entries.get(i)) else None)
    else:
        picked = {"rows": pool[:1]} if pool else refused("nothing logged to change")
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    delete = bool(args.get("delete"))
    held = _held(picked, "تحذف" if delete else "تعدّل", delete, args, ctx)
    if held:
        return held
    amount = args.get("amount")
    for r in rows:
        if delete:
            entries.delete(r["id"])
            continue
        current = entries.get(r["id"]) or {}
        data = dict(current.get("data") or {})
        extra = args.get("data") if isinstance(args.get("data"), dict) else {}
        if extra or (isinstance(amount, (int, float)) and not isinstance(amount, bool)):
            data.update(extra)
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                data["amount"] = amount
        else:
            data = None
        text, embed = args.get("text"), True
        if text is not None and (current.get("data") or {}).get("encrypted"):
            text, embed = encrypt_field(str(text)), False
        try:
            entries.update(r["id"], text=text, data=data, embed=embed)
        except KindError as exc:
            return refused(str(exc))
    verb = "حذفت" if delete else "عدّلت"
    return {"ok": True, "changed": len(rows), "reply": f"{verb} {_names(rows)} ✅"}


def _alias_filters(query: str) -> Tuple[Optional[str], Optional[str], str]:
    """(log/schedule kind, list, the rest of the query): «شو مهامي» is the tasks list,
    not the text «مهامي» — matched as text it filtered every task out."""
    kind = list_name = None
    rest = []
    for word in match_key(query).split():
        hit = None
        for form in (word, word[2:] if word.startswith("ال") else "", word.rstrip("ي")):
            hit = hit or (by_alias(form) if form else None)
        if hit is not None and hit.block == LIST and list_name is None:
            list_name = hit.name
        elif hit is not None and hit.block != LIST and kind is None:
            kind = hit.name
        else:
            rest.append(word)
    return kind, list_name, " ".join(rest)


def _route(kind: Optional[str], list_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Put a name in the slot it belongs to: the model sends kind="tasks" as often
    as list="tasks", and an alias («مهام») as often as the name."""
    for name in (kind, list_name):
        if not name:
            continue
        row = by_alias(match_key(name))
        if row is None and not get_kind(LIST, name) and not get_kind(LOG, name) \
                and not get_kind(SCHEDULE, name):
            continue
        if row is None:
            if get_kind(LIST, name) and not (name == kind and (
                    get_kind(LOG, name) or get_kind(SCHEDULE, name))):
                return None, name
            return name, None
        return (None, row.name) if row.block == LIST else (row.name, None)
    return kind, list_name


def recall(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    query = str(args.get("query") or "")
    kind, list_name = _route(str(args.get("kind") or "") or None, _list_name(args) or None)
    if kind is None and list_name is None:
        kind, list_name, query = _alias_filters(query)
    since = W.parse_bound(args.get("since"))
    until = W.parse_bound(args.get("until"), end=True)
    rows: List[Dict[str, Any]] = []
    if args.get("rang"):
        return _rang(since, until, query)
    if not list_name and (kind is None or get_kind(LOG, kind)):
        # Chat summaries are most of the log; they only come back when asked for.
        for k in [kind] if kind else [k for k in names(LOG) if k not in ("summary", "fact")]:
            # Every expense of the period, so the total is the server's, not the model's sum.
            rows += [_entry_row(e) for e in entries.list_entries(
                k, since=since, until=until, limit=_base.MAX_LIMIT if k == "expense" else SUMMARY_ROWS)]
    if not kind:
        found = items.list_items(list_name, limit=SUMMARY_ROWS)
        rows += [_item_row(i) for i in sorted(found, key=lambda i: bool(i.get("done")))]
    if not list_name and (kind is None or kind in USER_SCHEDULES):
        rows += [_schedule_row(s) for s in schedules.list_schedules(
            kind, status="pending", since=since, until=until, limit=SUMMARY_ROWS)
            if s.get("kind") in USER_SCHEDULES]
    narrowed = [r for r in rows if _matches_query(r, query)]
    # A filter already chose the rows; leftover words ("هالشهر") must not empty them.
    if narrowed or not (kind or list_name):
        rows = narrowed
    out = {"ok": True, "count": len(rows), "rows": rows[:MAX_ROWS]}
    if not list_name and kind in (None, "expense"):
        spent = _period_spending(since, until, lambda r: _matches_query(r, query),
                                 keep_all=bool(kind))
        if spent:
            out["spending"] = spent
    return out


def _period_spending(since, until, keep, *, keep_all: bool = False) -> Optional[Dict[str, Any]]:
    """The spending of every expense in the range, read whole (not the capped rows shown),
    narrowed by `keep`; with `keep_all`, a filter that matches none leaves them all (the
    same rule `recall` uses for its rows)."""
    rows = [_entry_row(e) for e in entries.each_in_range("expense", since=since, until=until)]
    kept = [r for r in rows if keep(r)]
    return _spent(kept if (kept or not keep_all) else rows)


def _spent(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """«قديش صرفت؟»: the total, count and per-category sums of every expense row, ready."""
    total, count = 0.0, 0
    by_category: Dict[str, float] = {}
    for r in rows:
        amount = _number((r.get("data") or {}).get("amount"))
        if r.get("kind") != "expense" or amount is None:
            continue
        total, count = total + amount, count + 1
        cat = str((r.get("data") or {}).get("category") or "other")
        by_category[cat] = by_category.get(cat, 0) + amount
    if not count:
        return None
    return {"total": round(total, 2), "count": count,
            "by_category": {k: round(v, 2) for k, v in by_category.items()},
            "note": "هاد المجموع الصح من كل الصفوف؛ استعمليه ولا تجمعي بنفسك."}


def _rang(since, until, query: str) -> Dict[str, Any]:
    """«شو فاتني؟»: reminders that already rang (the last day unless a range is given)."""
    start = since or W.now_utc() - timedelta(days=1)
    end = until or W.now_utc()
    rows = []
    for s in schedules.list_schedules("reminder", fired_since=start, limit=SUMMARY_ROWS):
        fired = W.aware_utc(s["fired_at"])
        if s.get("status") != "cancelled" and fired <= end:
            rows.append({**_schedule_row(s), "rang_at": W.iso(fired)})
    rows = [r for r in rows if _matches_query(r, query)]
    return {"ok": True, "count": len(rows), "rows": rows[:MAX_ROWS]}


def summarize(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    period = str(args.get("period") or "today")
    if period not in W.PERIODS:
        return refused(f"period must be one of {W.PERIODS}")
    start, end = W.period_range(period)
    focus = str(args.get("focus") or "")
    rows = [_entry_row(e) for e in entries.list_entries(since=start, until=end, limit=SUMMARY_ROWS)]
    rows += [_item_row(i) for i in items.touched_between(start, end, limit=SUMMARY_ROWS)]
    rows += [_schedule_row(s) for s in schedules.list_schedules(since=start, until=end,
                                                                limit=SUMMARY_ROWS)
             if s.get("kind") in USER_SCHEDULES]
    def _focused(r: Dict[str, Any]) -> bool:
        return not focus or (r.get("kind") == focus or r.get("list") == focus
                             or _matches_query(r, focus))
    rows = [r for r in rows if _focused(r)]
    spent = _period_spending(start, end, _focused)
    return {"ok": True, "period": period, "from": W.iso(start), "to": W.iso(end),
            "count": len(rows), "rows": rows[:SUMMARY_ROWS], **({"spending": spent} if spent else {}),
            "instruction": "لخّصي هالصفوف للمستخدم بجمل قصيرة."}


# ── lists ────────────────────────────────────────────────────────────────────

def list_add(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    name, text = _list_name(args), str(args.get("text") or "").strip()
    if not text:
        return refused("text is empty")
    if get_kind(LOG, name) and not get_kind(LIST, name):
        return refused(f"«{name}» is something that happened, not a list: "
                       f"call remember with kind={name}")
    due = None
    if args.get("due"):
        due = W.parse_when(args["due"])
        if due is None:
            return refused("could not read the due time", due=args["due"])
    qty = _number(args.get("qty"))
    same = match_key(text)
    for row in items.list_items(name, done=False):
        if match_key(row.get("text", "")) == same:
            return _add_to_existing(row, qty, due)
    data = {**(args.get("data") or {}), **({"qty": qty} if qty is not None else {})}
    try:
        iid = items.add(name, text, data or None, due=due,
                        priority=str(args.get("priority") or ""))
    except KindError as exc:
        return refused(str(exc))
    if not iid:
        return refused("not saved")
    return {"ok": True, "id": iid, "reply": f"ضفت «{text}» ✅"}


def _add_to_existing(row: Dict[str, Any], qty: Optional[float], due: Any) -> Dict[str, Any]:
    """The same open item again: «كمان حليب» adds to its quantity, a new time moves it;
    with nothing new it is only reported."""
    if qty is None and due is None:
        return {"ok": True, "id": row["id"], "already": True,
                "reply": f"«{row['text']}» موجودة أصلاً بالقائمة"}
    data = None
    if qty is not None:
        have = _number((row.get("data") or {}).get("qty")) or 1
        data = {**(row.get("data") or {}), "qty": have + qty}
    try:
        items.update(row["id"], data=data, due=due if due is not None else items._UNSET)
    except KindError as exc:
        return refused(str(exc))
    parts = ([f"صاروا {data['qty']:g}"] if data else []) + ([W.local_text(due)] if due else [])
    return {"ok": True, "id": row["id"], "updated": True,
            "reply": f"«{row['text']}» كانت موجودة، عدّلتها: {'، '.join(parts)} ✅"}


def _pick(args: Dict[str, Any], rows: List[Dict[str, Any]], getter) -> Dict[str, Any]:
    """``{"rows": [...]}`` for the target(s), or a refusal the model can act on."""
    if args.get("id"):
        row = getter(str(args["id"]))
        return {"rows": [row]} if row else refused("no row with that id")
    m = match_rows(str(args.get("match_text") or ""), rows)
    if m["status"] == "matched":
        # A near-spelling is a guess («فاتورة المي» → «فاتورة النت»): it waits for a yes.
        return {"rows": [m["row"]], "guessed": m["tier"] == "fuzzy"}
    if m["status"] == "ambiguous":
        if args.get("all_matching"):
            return {"rows": m["matches"]}
        return refused("ambiguous", needs_choice=True, candidates=[
            {"id": r["id"], "text": r["text"], **({"due": W.iso(r["due"])} if r.get("due") else {})}
            for r in m["matches"][:8]])
    return refused("not found" if m["status"] == "not_found" else "say which one")


def _names(rows: List[Dict[str, Any]]) -> str:
    shown = "» و«".join(r.get("text", "") for r in rows[:3])
    return f"«{shown}»" + (f" وكمان {len(rows) - 3}" if len(rows) > 3 else "")


def _held(picked: Dict[str, Any], verb: str, asks: bool, args: Dict[str, Any],
          ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """The question when the change waits for a yes (asked for, several rows, or a guess)."""
    rows = picked["rows"]
    if ctx.confirmed or not (asks or len(rows) > 1 or picked.get("guessed")):
        return None
    guess = f" (أقرب إشي لـ«{args.get('match_text')}»)" if picked.get("guessed") else ""
    return needs_confirmation(f"{verb} {_names(rows)}{guess}")


def _number(value: Any) -> Optional[float]:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _check_in(row: Dict[str, Any]) -> Dict[str, Any]:
    """«خلصت الجيم اليوم»: today is ticked for the habit; the habit itself stays open."""
    today = datetime.now(USER_TZ).date().isoformat()
    for e in entries.list_entries("habit", limit=200):
        data = e.get("data") or {}
        if data.get("habit_item_id") == row["id"] and data.get("date") == today:
            return {"ok": True, "already": True, "reply": f"«{row['text']}» مسجّلة اليوم أصلاً ✅"}
    entries.add("habit", row.get("text", ""), {"habit_item_id": row["id"], "date": today})
    return {"ok": True, "reply": f"سجّلت «{row['text']}» لليوم ✅"}


def list_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    name = _list_name(args) or None
    # Open items only, unless the ask is to reopen a done one.
    pool = items.list_items(name, done=None if args.get("done") is False else False)
    picked = _pick(args, pool, items.get)
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    delete = bool(args.get("delete"))
    verb = "تحذف" if delete else ("تخلّص" if args.get("done") else "تعدّل")
    held = _held(picked, verb, delete, args, ctx)
    if held:
        return held
    due: Any = None if args.get("no_due") else items._UNSET
    if args.get("due") and not args.get("no_due"):
        due = W.parse_when(args["due"])
        if due is None:
            return refused("could not read the due time", due=args["due"])
    move = _list_name({"list": args.get("move_to"), "project": args.get("move_to_project")}) or None
    extra = args.get("data") if isinstance(args.get("data"), dict) else {}
    qty = _number(args.get("qty"))
    replies = []
    for r in rows:
        if delete:
            items.delete(r["id"])
            continue
        if args.get("done") and r.get("list") == "habits":
            replies.append(_check_in(r)["reply"])
            continue
        data = None
        if extra or qty is not None:
            # Merged into what the row has: days, time, qty, repeat, details.
            data = {**(r.get("data") or {}), **extra, **({"qty": qty} if qty is not None else {})}
        try:
            items.update(r["id"], text=args.get("text"), done=args.get("done"), due=due, data=data,
                         priority=args.get("priority"), list_name=move)
        except KindError as exc:
            return refused(str(exc))
    if replies and len(replies) == len(rows):
        return {"ok": True, "changed": len(rows), "reply": "\n".join(replies)}
    done_verb = "حذفت" if delete else ("خلّصت" if args.get("done") else "عدّلت")
    return {"ok": True, "changed": len(rows), "reply": "\n".join([*replies, f"{done_verb} {_names(rows)} ✅"])}


# ── schedules ────────────────────────────────────────────────────────────────

def _minutes(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# A reminder that rang this recently can still be snoozed («أجّليه ربع ساعة»).
RANG_WINDOW = timedelta(hours=2)


def _anchor_time(row_id: str) -> Optional[Any]:
    """The time of an existing reminder or task, for «قبل الاجتماع بربع ساعة»."""
    row = schedules.get(row_id)
    if row and row.get("fire_at"):
        return W.aware_utc(row["fire_at"])
    item = items.get(row_id)
    return W.aware_utc(item["due"]) if item and item.get("due") else None


def _device_timer(args: Dict[str, Any]) -> Dict[str, Any]:
    """«طفّي المكيف بعد ساعة»: the device and the value, checked now, sent by the runner
    at the time (a `scene` row marked `asked`, so a scene does not cancel it)."""
    from app.brain.tools_world import _resolve_device
    from app.features.device_store import command_payload

    device = _resolve_device(str(args.get("device") or ""))
    if device is None:
        return refused("no device by that name")
    value = str(args.get("value") or args.get("action") or "").strip()
    res = command_payload(device, value, value)
    if not res.get("ok"):
        return refused("that device does not take this value", allowed=res.get("allowed"))
    label = device.get("label") or device["name"]
    return {"kind": "scene", "text": f"{label} → {res['payload']}",
            "payload": {"device": device["name"], "value": res["payload"], "asked": True}}


def schedule(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    kind, text = str(args.get("kind") or "reminder"), str(args.get("text") or "").strip()
    payload = None
    if args.get("important") and kind == "reminder":
        # Through a Focus only when he asked for that, never by default.
        payload = {"important": True, **({"break_focus": True} if args.get("break_focus") else {})}
    if args.get("device"):
        timer = _device_timer(args)
        if not timer.get("kind"):
            return timer
        kind, text, payload = timer["kind"], timer["text"], timer["payload"]
    # The model gives minutes or the user's words; the clock arithmetic is ours.
    minutes = _minutes(args.get("in_minutes"))
    if args.get("before_id"):
        anchor = _anchor_time(str(args["before_id"]))
        if anchor is None:
            return refused("no reminder or task with a time has that id")
        fire_at = anchor - timedelta(minutes=_minutes(args.get("before_minutes")) or 0)
        if fire_at <= W.now_utc():
            return refused("that time has already passed", when=W.local_text(fire_at))
    elif minutes is not None and minutes > 0:
        fire_at = W.now_utc() + timedelta(minutes=minutes)
    else:
        fire_at = W.parse_when(args.get("when"))
    if fire_at is None:
        return refused("could not read the time; pass in_minutes or the user's words as when",
                       when=args.get("when"))
    rule = W.recurrence_rule(args.get("recurrence"))
    if rule is None:
        return refused("recurrence must be daily|weekly|monthly|yearly or an RRULE")
    try:
        sid = schedules.add(kind, text, fire_at, payload, recurrence=rule)
    except KindError as exc:
        return refused(str(exc))
    if not sid:
        return refused("not saved")
    said = (f"بعمل «{text}»" if kind == "scene" else
            f"حطّيت منبه «{text}»" if payload else f"بذكّرك «{text}»")
    return {"ok": True, "id": sid, "when": W.local_text(fire_at),
            "reply": f"تمام، {said} {W.local_text(fire_at)} ⏰"}


def _device_timers() -> List[Dict[str, Any]]:
    """Timed device commands the user asked for: shown and cancellable like reminders."""
    return [s for s in schedules.list_schedules("scene", status="pending")
            if (s.get("payload") or {}).get("asked")]


def _rang_lately(row: Dict[str, Any]) -> bool:
    fired = row.get("fired_at")
    return bool(fired) and W.aware_utc(fired) >= W.now_utc() - RANG_WINDOW


def _skipped(row: Dict[str, Any]) -> Optional[Any]:
    """The occurrence after the next one, for «اليوم بس لا»; None when it does not repeat."""
    from app.services.schedule_runner import next_occurrence

    rule = str(row.get("recurrence") or "")
    if not rule:
        return None
    at = W.aware_utc(row["fire_at"])
    return next_occurrence(rule, at, at)


def schedule_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    # Reminders and the device timers he asked for: the daily nudge, a scene's own reverts and
    # sealed messages are not his to edit here.
    pool = schedules.list_schedules("reminder", status="pending") + _device_timers()
    known = {r["id"] for r in pool}
    # Just rang: a one-time reminder is no longer pending, but «أجّليه» still means it.
    pool += [r for r in schedules.list_schedules("reminder", fired_since=W.now_utc() - RANG_WINDOW)
             if r["id"] not in known and r.get("status") == "sent"]
    picked = _pick(args, pool, lambda i: next((r for r in pool if r["id"] == i), None))
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    cancel = bool(args.get("cancel"))
    held = _held(picked, "تلغي" if cancel else "تعدّل", cancel, args, ctx)
    if held:
        return held
    rule: Optional[str] = None
    if args.get("stop_repeat"):
        rule = ""
    elif args.get("recurrence"):
        rule = W.recurrence_rule(args["recurrence"])
        if not rule:
            return refused("recurrence must be daily|weekly|monthly|yearly or an RRULE")
    shift = _minutes(args.get("shift_minutes"))
    fire_at: Optional[Any] = None
    if args.get("when") and not shift:
        fire_at = W.parse_when(args["when"])
        if fire_at is None:
            return refused("could not read the time; pass shift_minutes or the user's words",
                           when=args["when"])
    moved = None
    for r in rows:
        if cancel:
            schedules.update(r["id"], status="cancelled")
            continue
        at = fire_at
        if args.get("skip_next"):
            at = _skipped(r)
            if at is None:
                return refused("it does not repeat; cancel it instead")
        elif shift:
            if r.get("recurrence") and _rang_lately(r):
                # A repeating one that just rang: snooze this ring, the series stays as it is.
                snooze = W.now_utc() + timedelta(minutes=shift)
                schedules.add(r.get("kind") or "reminder", r.get("text", ""), snooze)
                moved = snooze
                continue
            # From its own time, not from now: «أجّليه كمان نص ساعة» adds to what is set.
            base = max(W.aware_utc(r["fire_at"]), W.now_utc())
            at = base + timedelta(minutes=shift)
        status = "pending" if r.get("status") == "sent" and at else None
        payload = None
        flags = {k: args[k] for k in ("important", "break_focus") if isinstance(args.get(k), bool)}
        if flags and r.get("kind") == "reminder":
            payload = {**(r.get("payload") or {}), **flags}
        schedules.update(r["id"], text=args.get("text"), fire_at=at, recurrence=rule, status=status,
                         payload=payload)
        moved = at or moved
    if cancel:
        return {"ok": True, "changed": len(rows), "reply": f"لغيت {_names(rows)} ✅"}
    when = f" لـ{W.local_text(moved)}" if moved else ""
    return {"ok": True, "changed": len(rows), "when": W.local_text(moved) if moved else None,
            "reply": f"عدّلت {_names(rows)}{when} ✅"}
