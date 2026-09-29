"""Copy every old feature store into the three blocks (sandy_entries/items/schedules).

Dry run by default: prints counts per source and per target, plus three sample
mapped docs per source, and writes nothing. ``--apply`` writes. ``--user <id>``
limits it to one tenant. Old collections are only read, never changed.

Idempotent: every written doc carries ``migrated_from`` and a ``_id`` derived
from it, and a source doc whose id is already in the target is skipped.

    python3 scripts/migrate_to_blocks.py [--apply] [--user <id>]

Not migrated on purpose: sandy_facts (a derived search index of tasks, books,
habits and journal, which are migrated from their own stores), the ``memory``
blob (its ``facts`` array has no writer), sandy_reading_meta (yearly reading
goal), focus, scenes, gifts, shared content, guest usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (_ROOT, os.path.join(_ROOT, "cloud")) if p not in sys.path]

from app.blocks import entries, init_blocks, items, schedules  # noqa: E402
from app.blocks._base import ENTRIES, ITEMS, SCHEDULES  # noqa: E402
from app.blocks.kinds import LIST, LOG, SCHEDULE, KindError, validate  # noqa: E402
from app.utils.tenant_db import scoped  # noqa: E402
from app.utils.time import USER_TZ  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402

_ID_NS = uuid.UUID("5a4d7b2e-6c1f-4e0a-9b3d-8f2a1c7e5d40")
_ENC_PREFIX = "enc:"  # ltm_crypto's marker; ciphertext is copied as is, never decrypted
_NUDGE_HOUR = 8       # nudge_scheduler._SEND_HOUR

BLOCK_OF = {LOG: ENTRIES, LIST: ITEMS, SCHEDULE: SCHEDULES}


def target_id(collection: str, old_id: Any) -> str:
    """Same old doc → same new id, so links (habit → check-in) resolve before writing."""
    return uuid.uuid5(_ID_NS, f"{collection}:{old_id}").hex


# ── value helpers ────────────────────────────────────────────────────────────

def _dt(value: Any) -> Optional[datetime]:
    """Mongo's naive-UTC datetime or an ISO string → aware UTC datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    return None


def _day(value: Any, hour: int = 0) -> Optional[datetime]:
    """'YYYY-MM-DD' → that local day at ``hour``, as aware datetime."""
    try:
        d = datetime.fromisoformat(str(value or "")[:10]).date()
    except ValueError:
        return None
    return datetime.combine(d, time(hour), tzinfo=USER_TZ)


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _enc(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)


# ── mappers: old doc → (name, text, data, extra kwargs for the block's add) ─

Mapped = Tuple[str, str, Dict[str, Any], Dict[str, Any]]


class Ctx:
    """Per-run lookups of old docs another mapper links to (habit name, book title)."""

    def __init__(self, mongo_db):
        self._db = mongo_db
        self._cache: Dict[Tuple[str, str, str], Optional[Dict[str, Any]]] = {}

    def old(self, collection: str, doc_id: Any, tenant: str) -> Dict[str, Any]:
        key = (tenant, collection, str(doc_id))
        if key not in self._cache:
            coll = scoped(self._db, collection)
            self._cache[key] = coll.find_one({"_id": doc_id}) if coll is not None else None
        return self._cache[key] or {}


def m_task(d, ctx, uid) -> Mapped:
    done = bool(d.get("done"))
    return "tasks", _s(d.get("text")), {
        "notes": _s(d.get("notes")), "project": _s(d.get("project")),
        "due_date": _s(d.get("due_date"))}, {
        "done": done, "due": _dt(d.get("due_at")) or _day(d.get("due_date")),
        "priority": _s(d.get("priority")), "created_at": _dt(d.get("created_at")),
        "done_at": _dt(d.get("completed_at"))}


def m_shopping(d, ctx, uid) -> Mapped:
    return "shopping", _s(d.get("text")), {
        "category": _s(d.get("category")), "price": d.get("price"),
        "qty": d.get("qty"), "unit": _s(d.get("unit"))}, {
        "done": bool(d.get("done")), "created_at": _dt(d.get("created_at")),
        "done_at": _dt(d.get("bought_at"))}


def m_goal(d, ctx, uid) -> Mapped:
    status = _s(d.get("status")) or "active"
    done = status == "done"
    return "goals", _s(d.get("text")), {
        "status": status, "deadline": _s(d.get("deadline"))}, {
        "done": done, "due": _day(d.get("deadline")),
        "created_at": _dt(d.get("created_at")),
        "done_at": _dt(d.get("updated_at")) if done else None}


def m_book(d, ctx, uid) -> Mapped:
    status = _s(d.get("status"))
    return "reading", _s(d.get("title")), {
        "author": _s(d.get("author")), "category": _s(d.get("category")),
        "cover_url": _s(d.get("cover_url")), "total_pages": d.get("total_pages"),
        "current_page": d.get("current_page"), "rating": d.get("rating"),
        "fmt": _s(d.get("fmt")), "status": status,
        "notes": list(d.get("notes") or []), "quotes": list(d.get("quotes") or []),
        "started_at": _dt(d.get("started_at"))}, {
        "done": status == "done", "created_at": _dt(d.get("created_at")),
        "done_at": _dt(d.get("finished_at"))}


def m_habit(d, ctx, uid) -> Mapped:
    return "habits", _s(d.get("name")), {"archived": bool(d.get("archived"))}, {
        "created_at": _dt(d.get("created_at"))}


def m_plan(d, ctx, uid) -> Mapped:
    return "plans", _s(d.get("topic")), {
        "status": _s(d.get("status")), "points": list(d.get("points") or []),
        "plan_text": _s(d.get("plan_text")), "summary": _s(d.get("summary")),
        "started_at": _dt(d.get("started_at"))}, {
        "created_at": _dt(d.get("started_at"))}


def m_habit_log(d, ctx, uid) -> Mapped:
    habit = ctx.old("sandy_habits", d.get("habit_id"), uid)
    return "habit", _s(habit.get("name")), {
        "habit_item_id": target_id("sandy_habits", d.get("habit_id")),
        "date": _s(d.get("date"))}, {"at": _day(d.get("date"), 12)}


def m_expense(d, ctx, uid) -> Mapped:
    return "expense", _s(d.get("note")) or _s(d.get("category")), {
        "amount": d.get("amount"), "category": _s(d.get("category")),
        "note": _s(d.get("note"))}, {"at": _dt(d.get("at"))}


def m_journal(d, ctx, uid) -> Mapped:
    return "journal", _s(d.get("text")), {"date": _s(d.get("date"))}, {
        "at": _dt(d.get("at")) or _day(d.get("date"), 12)}


def m_reading_session(d, ctx, uid) -> Mapped:
    book = ctx.old("sandy_books", d.get("book_id"), uid)
    start, end = d.get("start_page"), d.get("end_page")
    pages = max(0, int(end) - int(start or 0)) if end is not None else None
    return "reading", _s(book.get("title")), {
        "book_item_id": target_id("sandy_books", d.get("book_id")),
        "book": _s(book.get("title")), "start_page": start, "end_page": end,
        "pages": pages, "paused_total_sec": d.get("paused_total_sec"),
        "state": _s(d.get("state")), "ended_at": _dt(d.get("ended_at"))}, {
        "at": _dt(d.get("started_at"))}


def m_user_fact(d, ctx, uid) -> Mapped:
    return "fact", _s(d.get("content")), {
        "subtype": "user_fact", "category": _s(d.get("category"))}, {
        "at": _dt(d.get("created_at"))}


def m_labeled_fact(d, ctx, uid) -> Mapped:
    """Free-form labels Sandy made up on the fly ("عائلة", "تفضيلات"...): facts, label kept."""
    return "fact", _s(d.get("content")), {
        "subtype": "labeled", "category": _s(d.get("label"))}, {
        "at": _dt(d.get("created_at"))}


def m_emotional(d, ctx, uid) -> Mapped:
    return "mood", _s(d.get("topic")), {
        "mood": _s(d.get("mood")), "encrypted": _enc(d.get("topic"))}, {
        "at": _dt(d.get("created_at"))}


def m_style(d, ctx, uid) -> Mapped:
    return "fact", _s(d.get("preference")), {
        "subtype": "style", "source_message": _s(d.get("source_message")),
        "encrypted": _enc(d.get("preference"))}, {"at": _dt(d.get("created_at"))}


def m_lesson(d, ctx, uid) -> Mapped:
    return "fact", _s(d.get("lesson")), {
        "subtype": "lesson", "encrypted": _enc(d.get("lesson"))}, {
        "at": _dt(d.get("created_at"))}


def m_relationship(d, ctx, uid) -> Mapped:
    relation, name = _s(d.get("relation")), _s(d.get("name"))
    return "fact", f"{relation}: {name}", {
        "subtype": "relationship", "relation": relation, "name": name}, {
        "at": _dt(d.get("created_at"))}


def m_interest(d, ctx, uid) -> Mapped:
    return "fact", _s(d.get("keyword")), {
        "subtype": "interest", "count": d.get("count"),
        "last_seen": _dt(d.get("last_seen"))}, {"at": _dt(d.get("created_at"))}


def m_milestone(d, ctx, uid) -> Mapped:
    return "fact", _s(d.get("context")), {
        "subtype": "milestone", "signal": _s(d.get("signal")),
        "event_date": _s(d.get("event_date")), "encrypted": _enc(d.get("context"))}, {
        "at": _dt(d.get("created_at"))}


def m_summary(d, ctx, uid) -> Mapped:
    return "summary", _s(d.get("summary")), {
        "thread_id": _s(d.get("thread_id")), "source_turns": d.get("source_turns")}, {
        "at": _dt(d.get("created_at")), "embedding": d.get("embedding") or None}


def m_photo(d, ctx, uid) -> Mapped:
    return "photo", _s(d.get("name")) or _s(d.get("user_caption")), {
        "name": _s(d.get("name")), "grid_id": _s(d.get("grid_id")),
        "file_unique_id": _s(d.get("file_unique_id")),
        "user_caption": _s(d.get("user_caption")), "ai_caption": _s(d.get("ai_caption")),
        "tags": list(d.get("tags") or [])}, {"at": _dt(d.get("created_at"))}


_SEND_STATE = {"pending": "pending", "sending": "pending", "failed": "failed", "sent": "sent"}


def m_reminder(d, ctx, uid) -> Mapped:
    return "reminder", _s(d.get("text")), {
        "note": _s(d.get("note")), "linked_task_id": _s(d.get("linked_task_id")),
        "parent_summary": _s(d.get("parent_summary")),
        "source_kind": _s(d.get("kind")) or "reminder",
        "series_at": _dt(d.get("series_at")), "sent_at": _dt(d.get("sent_at")),
        "last_error": _s(d.get("last_error"))}, {
        "fire_at": _dt(d.get("remind_at")), "recurrence": _s(d.get("recurrence")),
        "status": _SEND_STATE.get(_s(d.get("send_state")), "pending"),
        "created_at": _dt(d.get("created_at"))}


def m_future_message(d, ctx, uid) -> Mapped:
    return "message_to_future_self", _s(d.get("text")), {
        "encrypted": _enc(d.get("text")), "delivered_at": _dt(d.get("delivered_at"))}, {
        "fire_at": _dt(d.get("deliver_at")),
        "status": "sent" if d.get("delivered") else "pending",
        "created_at": _dt(d.get("created_at"))}


def m_scene_timer(d, ctx, uid) -> Mapped:
    device, value = _s(d.get("device")), _s(d.get("value"))
    return "scene", f"{device} → {value}", {
        "device": device, "value": value, "tries": d.get("tries")}, {
        "fire_at": _dt(d.get("fire_at"))}


def m_daily_nudge(d, ctx, uid) -> Mapped:
    nudge = d.get("nudge") or {}
    date = _s(d.get("_id")).rpartition(":")[2]
    return "daily_nudge", _s(nudge.get("text")), {
        "nudge_kind": _s(nudge.get("kind")), "qid": _s(nudge.get("qid")), "date": date}, {
        "fire_at": _day(date, _NUDGE_HOUR), "status": "sent",
        "created_at": _dt(d.get("created_at"))}


@dataclass(frozen=True)
class Source:
    collection: str
    tenant_field: str
    block: str
    mapper: Callable[[Dict[str, Any], Ctx, str], Mapped]
    query: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        label = self.query.get("label") or self.query.get("status")
        if isinstance(label, dict):
            label = "other labels"
        return f"{self.collection}[{label}]" if label else self.collection


def _mem(label: str, mapper) -> Source:
    return Source("sandy_memories", "chat_id", LOG, mapper, {"label": label})


# Linked targets (habits, books) come before what links to them.
SOURCES: Tuple[Source, ...] = (
    Source("sandy_tasks", "user_id", LIST, m_task),
    Source("sandy_shopping", "user_id", LIST, m_shopping),
    Source("sandy_goals", "chat_id", LIST, m_goal),
    Source("sandy_books", "user_id", LIST, m_book),
    Source("sandy_habits", "user_id", LIST, m_habit),
    Source("sandy_brainstorms", "chat_id", LIST, m_plan, {"status": "done"}),
    Source("sandy_habit_log", "user_id", LOG, m_habit_log),
    Source("sandy_expenses", "user_id", LOG, m_expense),
    Source("sandy_journal", "user_id", LOG, m_journal),
    Source("sandy_reading_sessions", "user_id", LOG, m_reading_session),
    _mem("user_fact", m_user_fact),
    _mem("emotional_memory", m_emotional),
    _mem("style_memory", m_style),
    _mem("lesson_learned", m_lesson),
    _mem("relationship", m_relationship),
    _mem("interest", m_interest),
    _mem("milestone", m_milestone),
    _mem("conversation_summary", m_summary),
    # Every other label, so a memory under a label nobody planned for is never dropped.
    Source("sandy_memories", "chat_id", LOG, m_labeled_fact,
           {"label": {"$nin": ["user_fact", "emotional_memory", "style_memory",
                               "lesson_learned", "relationship", "interest",
                               "milestone", "conversation_summary"]}}),
    Source("sandy_photos", "chat_id", LOG, m_photo),
    Source("sandy_reminders", "user_id", SCHEDULE, m_reminder),
    Source("sandy_future_messages", "chat_id", SCHEDULE, m_future_message),
    Source("sandy_scene_timers", "user_id", SCHEDULE, m_scene_timer),
    Source("sandy_daily_nudge", "user_id", SCHEDULE, m_daily_nudge),
)


@dataclass
class Report:
    read: Counter = field(default_factory=Counter)
    already: Counter = field(default_factory=Counter)
    invalid: Counter = field(default_factory=Counter)
    written: Counter = field(default_factory=Counter)
    targets: Counter = field(default_factory=Counter)
    samples: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    errors: List[str] = field(default_factory=list)


def _check(block: str, name: str, data: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    clean = validate(block, name, data)
    if block == SCHEDULE and not isinstance(extra.get("fire_at"), datetime):
        raise ValueError("no fire time")
    return clean


def _write(block: str, name: str, text: str, data, extra, *, doc_id, ref, mongo_db) -> str:
    common = {"migrated_from": ref, "doc_id": doc_id, "mongo_db": mongo_db}
    if block == LOG:
        return entries.add(name, text, data, embed=False, **extra, **common)
    if block == LIST:
        return items.add(name, text, data, **extra, **common)
    fire_at = extra.pop("fire_at")
    return schedules.add(name, text, fire_at, data, **extra, **common)


def _tenants(mongo_db, src: Source, user: Optional[str]) -> List[str]:
    if user:
        return [user]
    # Raw handle only to discover who owns data; every read and write below is scoped.
    found = mongo_db[src.collection].distinct(src.tenant_field, src.query)
    return sorted({str(t) for t in found if t not in (None, "")})


def _migrate_source(mongo_db, src: Source, uid: str, apply: bool, ctx: Ctx, report: Report) -> None:
    source = scoped(mongo_db, src.collection, field=src.tenant_field, bump=False)
    target = scoped(mongo_db, BLOCK_OF[src.block], bump=False)
    if source is None or target is None:
        return
    done = set(target.distinct("migrated_from.id", {"migrated_from.collection": src.collection}))
    for d in source.find(src.query):
        report.read[src.key] += 1
        old_id = str(d["_id"])
        if old_id in done:
            report.already[src.key] += 1
            continue
        try:
            name, text, data, extra = src.mapper(d, ctx, uid)
            data = _check(src.block, name, data, extra)
        except (KindError, ValueError, TypeError) as exc:
            report.invalid[src.key] += 1
            report.errors.append(f"{src.key} {old_id}: {exc}")
            continue
        report.targets[f"{BLOCK_OF[src.block]}:{name}"] += 1
        if len(report.samples[src.key]) < 3:
            report.samples[src.key].append({"user_id": uid, "kind": name, "text": text,
                                            "data": data, **extra})
        if apply:
            ref = {"collection": src.collection, "id": old_id}
            new_id = _write(src.block, name, text, data, dict(extra),
                            doc_id=target_id(src.collection, old_id), ref=ref,
                            mongo_db=mongo_db)
            if new_id:
                report.written[src.key] += 1


def run(mongo_db, *, apply: bool = False, user: Optional[str] = None) -> Report:
    if apply:
        init_blocks(mongo_db)
    report = Report()
    ctx = Ctx(mongo_db)
    for src in SOURCES:
        for uid in _tenants(mongo_db, src, user):
            with active_user_profile_context({"chat_id": uid}):
                _migrate_source(mongo_db, src, uid, apply, ctx, report)
    return report


def print_report(report: Report, apply: bool) -> None:
    print("MODE:", "APPLY" if apply else "DRY RUN (nothing written; pass --apply)")
    print("\nPer source: read / already migrated / invalid" + (" / written" if apply else ""))
    for src in SOURCES:
        k = src.key
        row = f"  {k:40} {report.read[k]:6} {report.already[k]:6} {report.invalid[k]:6}"
        print(row + (f" {report.written[k]:6}" if apply else ""))
    print("\nPer target (new docs):")
    for key, n in sorted(report.targets.items()):
        print(f"  {key:40} {n:6}")
    for line in report.errors[:50]:
        print("  invalid:", line)
    print("\nSamples:")
    for key, docs in report.samples.items():
        print(f"-- {key}")
        for doc in docs:
            print("   ", json.dumps(doc, ensure_ascii=False, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--user", help="only this tenant id")
    args = parser.parse_args(argv)

    from app.config import MONGODB_DB_NAME, MONGODB_URI
    from app.integrations.mongodb_store import init_mongo_connection

    if not MONGODB_URI:
        print("no database: set MONGODB_URI (and MONGODB_DB_NAME)", file=sys.stderr)
        return 1
    _, mongo_db = init_mongo_connection(MONGODB_URI, MONGODB_DB_NAME)
    report = run(mongo_db, apply=args.apply, user=args.user)
    print_report(report, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
