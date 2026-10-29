"""The tools that read and write the three blocks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.brain.categorize import categorize_later
from app.utils.ltm_crypto import decrypt_field, encrypt_field
from app.utils.time import USER_TZ
from app.blocks import _base, changes, entries, items, schedules
from app.blocks.kinds import LIST, LOG, SCHEDULE, KindError, by_alias, get_kind, names
from app.brain import lang, takeback
from app.brain import when as W
from app.brain.ctx import TurnCtx, needs_confirmation, refused
from app.brain.matching import match_rows
from app.brain.matching import match_key

logger = logging.getLogger(__name__)

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
           "text": lang.say("sealed_message") if sealed else decrypt_field(s.get("text", "")),
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
        eid = entries.add(kind, text, _known_data(LOG, kind, args.get("data")) or None,
                          source=ctx.source)
    except KindError as exc:
        return refused(str(exc))
    if not eid:
        return refused("not saved")
    out = {"ok": True, "id": eid, "reply": lang.say("logged", text=text)}
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


def undo(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«تراجعي»، «لا رجّعيه»، «غلطت رجّعيها»، «رجّعي الحليب»، «رجّعي آخر تلاتة»: what was
    deleted comes back as it was, what was changed gets its old values, what was added
    goes. With nothing named, everything the last change did (one reply, or one tool of a
    call), however much was said since; `match_text` names a row, `count` takes the last
    that many rows. Seven days back (`blocks.changes`). Devices are not undone."""
    recent = [c for c in changes.recent() if c.get("turn") != ctx.turn_id]
    if not recent:
        return refused("nothing to undo", reply=lang.say("undo_nothing"))
    said = str(args.get("match_text") or "").strip()
    count = _minutes(args.get("count"))
    if said:
        rows = [{"id": c["_id"], "text": decrypt_field(c.get("label") or "")} for c in recent]
        m = match_rows(said, rows)
        if m["status"] not in ("matched", "ambiguous") or m.get("tier") == "fuzzy":
            return refused("nothing by that name to undo", reply=lang.say("undo_not_found", said=said))
        picked = [next(c for c in recent if c["_id"] == m["matches"][0]["id"])]
    elif count and count > 0:
        picked = recent[:count]
    else:
        picked = [c for c in recent if c.get("turn") == recent[0].get("turn")]
    done = changes.undo(picked)
    names = list(dict.fromkeys(decrypt_field(c.get("label") or "") for c in picked))
    if not done:
        return refused("nothing put back", reply=lang.say("undo_failed"))
    return {"ok": True, "undone": done, "items": names,
            "reply": lang.say("undo_done",
                              names=lang.say("sep").join(f"«{n}»" for n in names[:3] if n))}


def log_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«لا قصدي أربعين مش خمسين»، «نقلت بيت جديد»: a log row is changed, not logged
    again. With no id and no text, the newest row of the kind. Encrypted rows are sealed
    again and never embedded. Deleting is `log_delete`."""
    kind, pool, getter = _log_pool(args)
    picked = _log_targets(args, ctx, kind, pool, getter)
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    held = _held(picked, "held_change", ctx)
    if held:
        return held
    amount = args.get("amount")
    before = [entries.get(r["id"]) for r in rows]
    for r in rows:
        current = entries.get(r["id"]) or {}
        data = dict(current.get("data") or {})
        extra = _known_data(LOG, str(current.get("kind") or kind or ""), args.get("data"))
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
    if _same([b for b in before if b], entries.get):
        return refused("nothing changed", reply=lang.say("nothing_changed"))
    takeback.corrected(ctx, rows)
    return {"ok": True, "changed": len(rows), "reply": lang.say("edited", names=_names(rows))}


def _log_pool(args: Dict[str, Any]):
    kind = str(args.get("kind") or "").strip() or None
    pool = [_entry_row(e) for e in entries.list_entries(kind, exclude=("summary",), limit=MAX_ROWS * 2)]

    def getter(i):
        return _entry_row(e) if (e := entries.get(i)) else None
    return kind, pool, getter


def _log_targets(args: Dict[str, Any], ctx: TurnCtx, kind: Optional[str], pool, getter):
    """The log rows a change or a delete names: by id, by name, else the newest of the kind."""
    picked = _held_rows(ctx, getter)
    if picked is not None:
        return picked
    if args.get("id") or args.get("ids") or args.get("match_text"):
        return _named(args, pool, getter)
    if pool:
        return {"rows": pool[:1]}
    return refused("nothing logged",
                   reply=lang.say("nothing_logged", kind=_kind_name(kind) or lang.say("something")))


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
    for row in items.match_pool(name, done=False):
        if match_key(row.get("text", "")) == same:
            return _add_to_existing(row, qty, due)
    data = {**_known_data(LIST, name, args.get("data")), **({"qty": qty} if qty is not None else {})}
    try:
        iid = items.add(name, text, data or None, due=due,
                        priority=str(args.get("priority") or ""))
    except KindError as exc:
        return refused(str(exc))
    if not iid:
        return refused("not saved")
    return {"ok": True, "id": iid, "reply": lang.say("added", text=text)}


def _add_to_existing(row: Dict[str, Any], qty: Optional[float], due: Any) -> Dict[str, Any]:
    """The same open item again: «كمان حليب» adds to its quantity, a new time moves it;
    with nothing new it is only reported."""
    if qty is None and due is None:
        return {"ok": True, "id": row["id"], "already": True,
                "reply": lang.say("already_listed", text=row["text"])}
    data = None
    if qty is not None:
        have = _number((row.get("data") or {}).get("qty")) or 1
        data = {**(row.get("data") or {}), "qty": have + qty}
    try:
        items.update(row["id"], data=data, due=due if due is not None else items._UNSET)
    except KindError as exc:
        return refused(str(exc))
    parts = ([lang.say("qty_now", qty=f"{data['qty']:g}")] if data else []) + (
        [W.local_text(due)] if due else [])
    return {"ok": True, "id": row["id"], "updated": True,
            "reply": lang.say("existed_updated", text=row["text"], parts=lang.say("sep").join(parts))}


def _kind_name(kind: Optional[str]) -> str:
    row = get_kind(LOG, kind) if kind else None
    return (row.en if lang.current() == lang.EN else row.ar) if row else ""


def _not_found(said: str, closest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Nothing by that name: said so, with the nearest spelling when there is one. A near
    spelling is never acted on («فاتورة المي» is not «فاتورة النت»)."""
    reply = lang.say("not_found_named", said=said) if said else lang.say("not_found")
    if closest is not None:
        return refused("not found", closest={"id": closest["id"], "text": closest["text"]},
                       reply=lang.say("not_found_closest", reply=reply, closest=closest["text"]))
    return refused("not found", reply=f"{reply}.")


def _pick(args: Dict[str, Any], rows: List[Dict[str, Any]], getter) -> Dict[str, Any]:
    """``{"rows": [...]}`` for the target(s), or a refusal the model can act on."""
    if args.get("id"):
        row = getter(str(args["id"]))
        return {"rows": [row]} if row else _not_found("")
    said = str(args.get("match_text") or "").strip()
    m = match_rows(said, rows)
    if m["status"] == "matched" and m["tier"] == "fuzzy":
        return _not_found(said, m["row"])
    if m["status"] == "matched":
        return {"rows": [m["row"]]}
    if m["status"] == "ambiguous":
        if args.get("all_matching") and m["tier"] != "fuzzy":
            return {"rows": m["matches"]}
        if m["tier"] == "fuzzy":
            return _not_found(said, m["matches"][0])
        return refused("ambiguous", needs_choice=True, candidates=[
            {"id": r["id"], "text": r["text"], **({"due": W.iso(r["due"])} if r.get("due") else {})}
            for r in m["matches"][:8]])
    return _not_found(said) if m["status"] == "not_found" else refused("say which one")


def _named(args: Dict[str, Any], rows: List[Dict[str, Any]], getter) -> Dict[str, Any]:
    """`_pick`, and several rows named at once by `ids`; an id that is not there is counted
    (`missing`), and none there at all is «ما لقيت»."""
    ids = list(dict.fromkeys([str(i) for i in [args.get("id"), *(args.get("ids") or [])] if i]))
    if not ids:
        return _pick(args, rows, getter)
    found = [r for r in (getter(i) for i in ids) if r]
    if not found:
        return _not_found("")
    return {"rows": found, "missing": len(ids) - len(found)}


def _held_rows(ctx: TurnCtx, getter) -> Optional[Dict[str, Any]]:
    """On a yes, the rows the question named, by id: a row added since is never caught by
    a search run again. None when this is not such a replay."""
    if not (ctx.confirmed and ctx.held_ids):
        return None
    rows = [r for r in (getter(i) for i in ctx.held_ids) if r]
    return {"rows": rows} if rows else refused(
        "the rows asked about are gone", reply=lang.say("held_gone"))


def _names(rows: List[Dict[str, Any]]) -> str:
    """«a» و«b» وكمان 3 / «a», «b» and 3 more."""
    names = [f"«{r.get('text', '')}»" for r in rows[:3]]
    if len(rows) > 3:
        return lang.say("names_more", names=lang.say("sep").join(names), n=len(rows) - 3)
    if len(names) > 1:
        return lang.say("names_last", names=lang.say("sep").join(names[:-1]), last=names[-1])
    return "".join(names)


# More rows than this in one change is a bulk one, and waits for a yes; one row, or a few
# named ones, run at once.
BULK_ROWS = 5


def _held(picked: Dict[str, Any], verb: str, ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """The question when the change is a bulk one and waits for a yes; ``verb`` names its
    phrase (`held_change`, `held_finish`), whose first word `confirm` reads a yes by."""
    rows = picked["rows"]
    if ctx.confirmed or len(rows) <= BULK_ROWS:
        return None
    return needs_confirmation(lang.say(verb, names=_names(rows)), [r["id"] for r in rows])


def _same(before: List[Dict[str, Any]], fetch) -> bool:
    """Every row is as it was before the edit: nothing the user asked for was changed."""
    return all(fetch(r["id"]) == r for r in before)


def _number(value: Any) -> Optional[float]:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _check_in(row: Dict[str, Any]) -> Dict[str, Any]:
    """«خلصت الجيم اليوم»: today is ticked for the habit; the habit itself stays open."""
    today = datetime.now(USER_TZ).date().isoformat()
    for e in entries.list_entries("habit", limit=200):
        data = e.get("data") or {}
        if data.get("habit_item_id") == row["id"] and data.get("date") == today:
            return {"ok": True, "already": True,
                    "reply": lang.say("checked_already", text=row["text"])}
    entries.add("habit", row.get("text", ""), {"habit_item_id": row["id"], "date": today})
    return {"ok": True, "reply": lang.say("checked_today", text=row["text"])}


def list_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    name = _list_name(args) or None
    # Open items only, unless the ask is to reopen a done one.
    pool = items.match_pool(name, done=None if args.get("done") is False else False)
    picked = _held_rows(ctx, items.get) or _named(args, pool, items.get)
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    held = _held(picked, "held_finish" if args.get("done") else "held_change", ctx)
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
    before = [items.get(r["id"]) for r in rows]
    for r in rows:
        if args.get("done") and r.get("list") == "habits":
            replies.append(_check_in(r)["reply"])
            continue
        data = None
        if extra or qty is not None:
            # Merged into what the row has: days, time, qty, repeat, details.
            data = {**(r.get("data") or {}), **_known_data(LIST, str(r.get("list") or ""), extra),
                    **({"qty": qty} if qty is not None else {})}
        try:
            items.update(r["id"], text=args.get("text"), done=args.get("done"), due=due, data=data,
                         priority=args.get("priority"), list_name=move)
        except KindError as exc:
            return refused(str(exc))
    if replies and len(replies) == len(rows):
        return {"ok": True, "changed": len(rows), "reply": "\n".join(replies)}
    if not replies and _same([b for b in before if b], items.get):
        return refused("nothing changed", reply=lang.say("nothing_changed"))
    takeback.corrected(ctx, rows)
    said = lang.say("finished" if args.get("done") else "edited", names=_names(rows))
    return {"ok": True, "changed": len(rows), "reply": "\n".join([*replies, said])}


# ── schedules ────────────────────────────────────────────────────────────────

def _minutes(value: Any) -> Optional[int]:
    """Whole minutes from a number or a number written as text («30»); None otherwise."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# A time the tool could not read goes back to the model as what to do next, never a dead end.
_ASK_TIME = ("could not read the time: in_minutes is a whole number of minutes from now above 0 "
             "(«in half an hour» = 30), when is the user's own words («at 5», «بكرا الصبح»); if "
             "neither is clear, ask the user when")


def _known_data(block: str, kind: str, data: Any) -> Dict[str, Any]:
    """The model's ``data`` without the fields the kind does not have («time» on a task):
    set aside quietly, so a row is never refused for a detail it cannot hold."""
    row = get_kind(block, kind) if kind else None
    data = dict(data) if isinstance(data, dict) else {}
    if row is None:
        return data
    dropped = sorted(k for k in data if k not in row.fields)
    if dropped:
        logger.info("[brain] %s %s: set aside data fields %s", block, kind, dropped)
    return {k: v for k, v in data.items() if k in row.fields}


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
    if kind == "task":
        return refused("a task is made with task_create, after the user's yes")
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
    if args.get("in_minutes") not in (None, "") and (minutes is None or minutes < 0):
        return refused(_ASK_TIME, in_minutes=args.get("in_minutes"))
    if args.get("before_id"):
        anchor = _anchor_time(str(args["before_id"]))
        if anchor is None:
            return refused("no reminder or task with a time has that id")
        fire_at = anchor - timedelta(minutes=_minutes(args.get("before_minutes")) or 0)
        if fire_at <= W.now_utc():
            return refused("that time has already passed", when=W.local_text(fire_at))
    elif minutes is not None and minutes > 0:
        fire_at = W.now_utc() + timedelta(minutes=minutes)
    elif minutes == 0 or W.is_now(args.get("when")):
        fire_at = W.now_utc() + W.NOW_DELAY
    else:
        fire_at = W.parse_when(args.get("when"))
    if fire_at is None:
        return refused(_ASK_TIME, when=args.get("when"))
    rule = W.recurrence_rule(args.get("recurrence"))
    if rule is None:
        return refused("recurrence must be daily|weekly|monthly|yearly or an RRULE")
    try:
        sid = schedules.add(kind, text, fire_at, payload, recurrence=rule)
    except KindError as exc:
        return refused(str(exc))
    if not sid:
        return refused("not saved")
    if args.get("device"):
        takeback.set_for_later(ctx, payload["device"], payload["value"])
    said = "scheduled_scene" if kind == "scene" else "scheduled_alarm" if payload else "scheduled"
    return {"ok": True, "id": sid, "when": W.local_text(fire_at),
            "reply": lang.say(said, text=text, time=W.local_text(fire_at))}


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
    return next_occurrence(rule, schedules.series_anchor(row), W.aware_utc(row["fire_at"]))


def _reminders() -> List[Dict[str, Any]]:
    """Reminders and the device timers he asked for: the daily nudge, a scene's own reverts
    and sealed messages are not his to edit or cancel here."""
    return schedules.list_schedules("reminder", status="pending") + _device_timers()


def schedule_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    pool = _reminders()
    known = {r["id"] for r in pool}
    # Just rang: a one-time reminder is no longer pending, but «أجّليه» still means it.
    pool += [r for r in schedules.list_schedules("reminder", fired_since=W.now_utc() - RANG_WINDOW)
             if r["id"] not in known and r.get("status") == "sent"]
    def getter(i):
        return next((r for r in pool if r["id"] == i), None)

    picked = _held_rows(ctx, getter) or _named(args, pool, getter)
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    held = _held(picked, "held_change", ctx)
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
    before = [schedules.get(r["id"]) for r in rows]
    for r in rows:
        at = fire_at
        if args.get("skip_next"):
            at = _skipped(r)
            if at is None:
                return refused("it does not repeat; cancel it instead")
        elif shift:
            if _rang_lately(r):
                # Just rang: snooze this ring (a repeat's series stays as it is), as the
                # notification's «later» does.
                schedules.snooze(r, shift, W.now_utc())
                moved = W.now_utc() + timedelta(minutes=shift)
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
                         payload=payload, keep_series=bool(args.get("skip_next")))
        moved = at or moved
    if _same([b for b in before if b], schedules.get) and not moved:
        return refused("nothing changed", reply=lang.say("nothing_changed"))
    reply = (lang.say("edited_to", names=_names(rows), time=W.local_text(moved)) if moved
             else lang.say("edited", names=_names(rows)))
    return {"ok": True, "changed": len(rows), "when": W.local_text(moved) if moved else None,
            "reply": reply}


# ── deleting: one tool per block, so a delete is never a flag an edit forgets ─────

def _remove(picked: Dict[str, Any], ctx: TurnCtx, ask: str, said: str, remove,
            everything: bool) -> Dict[str, Any]:
    """Deletes (or cancels) the rows at once; a bulk one (the whole list or kind, or more
    than BULK_ROWS rows) waits for one yes."""
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    if not rows:
        return refused("nothing there", reply=lang.say("nothing_there"))
    if not ctx.confirmed and (everything or len(rows) > BULK_ROWS):
        return needs_confirmation(lang.say(ask, names=_names(rows)), [r["id"] for r in rows])
    gone = [r for r in rows if remove(r["id"])]
    if not gone:
        return _not_found("")
    missing = picked.get("missing", 0) + len(rows) - len(gone)
    reply = lang.say(said, names=_names(gone)) + (lang.say("missing", n=missing) if missing else "")
    return {"ok": True, "changed": len(gone), "reply": reply}


def list_delete(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«شيلي الحليب»، «احذفي مهمة الجيم»، «فضّي قائمة التسوق»."""
    name = _list_name(args) or None
    everything = bool(args.get("everything"))
    if everything and not name:
        return refused("everything needs a list", reply=lang.say("which_list"))
    pool = items.match_pool(name, done=False)
    picked = _held_rows(ctx, items.get) or (
        {"rows": pool} if everything else _named(args, pool, items.get))
    picked = takeback.not_corrected("list_delete", picked, ctx)
    return _remove(picked, ctx, "held_delete", "deleted", items.delete, everything)


def log_delete(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«احذفي آخر مصروف»، «احذفي هالمصروف»، «انسي إني بحب القهوة»."""
    kind, pool, getter = _log_pool(args)
    everything = bool(args.get("everything"))
    if everything and not kind:
        return refused("everything needs a kind", reply=lang.say("what_to_delete"))
    picked = _held_rows(ctx, getter) or (
        {"rows": pool} if everything else _log_targets(args, ctx, kind, pool, getter))
    picked = takeback.not_corrected("log_delete", picked, ctx)
    return _remove(picked, ctx, "held_delete", "deleted", entries.delete, everything)


def schedule_cancel(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«الغي تذكير الدوا»، «الغي كل التذكيرات»."""
    pool = _reminders()

    def getter(i):
        return next((r for r in pool if r["id"] == i), None)

    def cancel(i):
        return schedules.update(i, status="cancelled")

    everything = bool(args.get("everything"))
    picked = _held_rows(ctx, getter) or (
        {"rows": pool} if everything else _named(args, pool, getter))
    return _remove(picked, ctx, "held_cancel", "cancelled_rows", cancel, everything)
