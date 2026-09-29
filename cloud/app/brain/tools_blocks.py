"""The tools that read and write the three blocks."""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

from app.agent.ltm_crypto import decrypt_field, encrypt_field
from app.blocks import entries, items, schedules
from app.blocks.kinds import LIST, LOG, SCHEDULE, KindError, by_alias, get_kind, names
from app.brain import when as W
from app.brain.ctx import TurnCtx, needs_confirmation, refused
from app.brain.matching import match_rows
from app.features.tasks_matcher import _task_match_key

MAX_ROWS = 30
SUMMARY_ROWS = 200
# graph._SIGNIFICANT_MOODS: the moods the old turn kept an emotional moment for.
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


def _schedule_row(s: Dict[str, Any]) -> Dict[str, Any]:
    row = {"id": s["id"], "kind": s.get("kind"), "text": s.get("text", ""),
           "when": W.iso(s.get("fire_at")), "status": s.get("status")}
    if s.get("recurrence"):
        row["recurrence"] = s["recurrence"]
    return row


def _matches_query(row: Dict[str, Any], query: str) -> bool:
    words = [w for w in _task_match_key(query).split() if len(w) >= 2]
    if not words:
        return True
    hay = _task_match_key(" ".join(str(v) for v in row.values()))
    return any(w in hay for w in words)


def _list_name(args: Dict[str, Any]) -> str:
    name = str(args.get("list") or "").strip()
    project = str(args.get("project") or "").strip()
    return f"project:{project}" if name == "project" and project else name


# ── remember / recall / summarize ────────────────────────────────────────────

def _mood(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """The old emotional moment as a `mood` entry: a significant mood, the user's
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
    return {"ok": bool(eid), "id": eid, "reply": f"سجّلتها ✅ «{text}»"} if eid \
        else refused("not saved")


def _alias_filters(query: str) -> Tuple[Optional[str], Optional[str], str]:
    """(log/schedule kind, list, the rest of the query): «شو مهامي» is the tasks list,
    not the text «مهامي» — matched as text it filtered every task out."""
    kind = list_name = None
    rest = []
    for word in _task_match_key(query).split():
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


def recall(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    query = str(args.get("query") or "")
    kind = str(args.get("kind") or "") or None
    list_name = _list_name(args) or None
    if kind is None and list_name is None:
        kind, list_name, query = _alias_filters(query)
    since = W.parse_bound(args.get("since"))
    until = W.parse_bound(args.get("until"), end=True)
    rows: List[Dict[str, Any]] = []
    if not list_name and (kind is None or get_kind(LOG, kind)):
        # Chat summaries are most of the log; they only come back when asked for.
        for k in [kind] if kind else [k for k in names(LOG) if k not in ("summary", "fact")]:
            rows += [_entry_row(e) for e in entries.list_entries(
                k, since=since, until=until, limit=SUMMARY_ROWS)]
    if not kind:
        found = items.list_items(list_name, limit=SUMMARY_ROWS)
        rows += [_item_row(i) for i in sorted(found, key=lambda i: bool(i.get("done")))]
    if not list_name and (kind is None or get_kind(SCHEDULE, kind)):
        rows += [_schedule_row(s) for s in schedules.list_schedules(
            kind, status="pending", since=since, until=until, limit=SUMMARY_ROWS)]
    narrowed = [r for r in rows if _matches_query(r, query)]
    # A filter already chose the rows; leftover words ("هالشهر") must not empty them.
    if narrowed or not (kind or list_name):
        rows = narrowed
    return {"ok": True, "count": len(rows), "rows": rows[:MAX_ROWS]}


def summarize(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    period = str(args.get("period") or "today")
    if period not in W.PERIODS:
        return refused(f"period must be one of {W.PERIODS}")
    start, end = W.period_range(period)
    focus = str(args.get("focus") or "")
    rows = [_entry_row(e) for e in entries.list_entries(since=start, until=end, limit=SUMMARY_ROWS)]
    for i in items.list_items(limit=SUMMARY_ROWS):
        created, done_at = i.get("created_at"), i.get("done_at")
        if _in(created, start, end) or _in(done_at, start, end):
            rows.append(_item_row(i))
    rows += [_schedule_row(s) for s in schedules.list_schedules(since=start, until=end,
                                                                limit=SUMMARY_ROWS)]
    if focus:
        rows = [r for r in rows if r.get("kind") == focus or r.get("list") == focus
                or _matches_query(r, focus)]
    return {"ok": True, "period": period, "from": W.iso(start), "to": W.iso(end),
            "count": len(rows), "rows": rows[:SUMMARY_ROWS],
            "instruction": "لخّصي هالصفوف للمستخدم بجمل قصيرة."}


def _in(dt: Any, start, end) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return start <= dt < end


# ── lists ────────────────────────────────────────────────────────────────────

def list_add(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    name, text = _list_name(args), str(args.get("text") or "").strip()
    if not text:
        return refused("text is empty")
    if get_kind(LOG, name) and not get_kind(LIST, name):
        return refused(f"«{name}» is something that happened, not a list: "
                       f"call remember with kind={name}")
    same = _task_match_key(text)
    for row in items.list_items(name, done=False):
        if _task_match_key(row.get("text", "")) == same:
            return {"ok": True, "id": row["id"], "already": True,
                    "reply": f"«{text}» موجودة أصلاً بالقائمة"}
    due = None
    if args.get("due"):
        due = W.parse_when(args["due"])
        if due is None:
            return refused("could not read the due time", due=args["due"])
    try:
        iid = items.add(name, text, args.get("data") or None, due=due,
                        priority=str(args.get("priority") or ""))
    except KindError as exc:
        return refused(str(exc))
    if not iid:
        return refused("not saved")
    return {"ok": True, "id": iid, "reply": f"ضفت «{text}» ✅"}


def _pick(args: Dict[str, Any], rows: List[Dict[str, Any]], getter) -> Dict[str, Any]:
    """``{"rows": [...]}`` for the target(s), or a refusal the model can act on."""
    if args.get("id"):
        row = getter(str(args["id"]))
        return {"rows": [row]} if row else refused("no row with that id")
    m = match_rows(str(args.get("match_text") or ""), rows)
    if m["status"] == "matched":
        return {"rows": [m["row"]]}
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


def list_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    name = _list_name(args) or None
    # Open items only, unless the ask is to reopen a done one.
    pool = items.list_items(name, done=None if args.get("done") is False else False)
    picked = _pick(args, pool, items.get)
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    delete = bool(args.get("delete"))
    if (delete or len(rows) > 1) and not ctx.confirmed:
        verb = "تحذف" if delete else "تعدّل"
        return needs_confirmation(f"{verb} {_names(rows)}")
    due: Any = items._UNSET
    if args.get("due"):
        due = W.parse_when(args["due"])
        if due is None:
            return refused("could not read the due time", due=args["due"])
    for r in rows:
        if delete:
            items.delete(r["id"])
        else:
            items.update(r["id"], text=args.get("text"), done=args.get("done"), due=due)
    verb = "حذفت" if delete else ("خلّصت" if args.get("done") else "عدّلت")
    return {"ok": True, "changed": len(rows), "reply": f"{verb} {_names(rows)} ✅"}


# ── schedules ────────────────────────────────────────────────────────────────

def schedule(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    kind, text = str(args.get("kind") or "reminder"), str(args.get("text") or "").strip()
    fire_at = W.parse_when(args.get("when"))
    if fire_at is None:
        return refused("could not read `when` as a future time", when=args.get("when"))
    rule = W.recurrence_rule(args.get("recurrence"))
    if rule is None:
        return refused("recurrence must be daily|weekly|monthly|yearly or an RRULE")
    try:
        sid = schedules.add(kind, text, fire_at, recurrence=rule)
    except KindError as exc:
        return refused(str(exc))
    if not sid:
        return refused("not saved")
    return {"ok": True, "id": sid, "when": W.iso(fire_at),
            "reply": f"تمام، بذكّرك «{text}» {W.iso(fire_at)} ⏰"}


def schedule_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    pool = schedules.list_schedules(status="pending")
    picked = _pick(args, pool, schedules.get)
    if "rows" not in picked:
        return picked
    rows = picked["rows"]
    cancel = bool(args.get("cancel"))
    if (cancel or len(rows) > 1) and not ctx.confirmed:
        verb = "تلغي" if cancel else "تعدّل"
        return needs_confirmation(f"{verb} {_names(rows)}")
    fire_at: Optional[Any] = None
    if args.get("when"):
        fire_at = W.parse_when(args["when"])
        if fire_at is None:
            return refused("could not read `when` as a future time", when=args["when"])
    for r in rows:
        if cancel:
            schedules.update(r["id"], status="cancelled")
        else:
            schedules.update(r["id"], text=args.get("text"), fire_at=fire_at)
    verb = "لغيت" if cancel else "عدّلت"
    return {"ok": True, "changed": len(rows), "reply": f"{verb} {_names(rows)} ✅"}

