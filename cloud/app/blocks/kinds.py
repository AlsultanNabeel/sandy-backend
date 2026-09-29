"""The kinds table: every log kind, list and schedule kind, in one place.

Adding a feature means adding a row to KINDS. A row names its block, labels,
SF Symbol icon and the ``data`` fields it accepts with their types. Every
field is optional; a key that is not declared is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Tuple

LOG = "log"
LIST = "list"
SCHEDULE = "schedule"
BLOCKS = (LOG, LIST, SCHEDULE)

# A row whose name ends with ":" matches any "<prefix><suffix>" name.
_PREFIX_MARK = ":"


class KindError(ValueError):
    """Unknown kind, or ``data`` that does not match its row."""


@dataclass(frozen=True)
class Kind:
    name: str
    block: str
    ar: str
    en: str
    icon: str
    fields: Mapping[str, Any] = field(default_factory=dict)


_S, _I, _F, _B, _L, _D, _T = str, int, float, bool, list, dict, datetime

KINDS: Tuple[Kind, ...] = (
    # ── LOG (sandy_entries) ──────────────────────────────────────────────────
    Kind("fact", LOG, "معلومة", "Fact", "brain", {
        "subtype": _S, "category": _S, "relation": _S, "name": _S,
        "count": _I, "source_message": _S, "signal": _S, "event_date": _S,
        "last_seen": _T, "encrypted": _B}),
    Kind("reading", LOG, "جلسة قراءة", "Reading session", "book", {
        "book_item_id": _S, "book": _S, "start_page": _I, "end_page": _I,
        "pages": _I, "paused_total_sec": _I, "state": _S, "ended_at": _T}),
    Kind("expense", LOG, "مصروف", "Expense", "creditcard", {
        "amount": _F, "category": _S, "note": _S}),
    Kind("habit", LOG, "عادة", "Habit check-in", "checkmark.circle", {
        "habit_item_id": _S, "date": _S}),
    Kind("mood", LOG, "مزاج", "Mood", "face.smiling", {
        "mood": _S, "encrypted": _B}),
    Kind("journal", LOG, "يوميات", "Journal", "book.closed", {"date": _S}),
    Kind("health", LOG, "صحة", "Health", "heart", {
        "metric": _S, "value": _F, "unit": _S}),
    Kind("photo", LOG, "صورة", "Photo", "photo", {
        "name": _S, "grid_id": _S, "file_unique_id": _S, "user_caption": _S,
        "ai_caption": _S, "tags": _L}),
    Kind("note", LOG, "ملاحظة", "Note", "note.text"),
    Kind("summary", LOG, "ملخص", "Summary", "text.alignleft", {
        "thread_id": _S, "source_turns": _I}),

    # ── LISTS (sandy_items) ──────────────────────────────────────────────────
    Kind("tasks", LIST, "المهام", "Tasks", "checklist", {
        "notes": _S, "project": _S, "due_date": _S}),
    Kind("shopping", LIST, "التسوق", "Shopping", "cart", {
        "category": _S, "price": _F, "qty": _F, "unit": _S}),
    Kind("goals", LIST, "الأهداف", "Goals", "target", {
        "status": _S, "deadline": _S}),
    Kind("reading", LIST, "القراءة", "Reading list", "books.vertical", {
        "author": _S, "category": _S, "cover_url": _S, "total_pages": _I,
        "current_page": _I, "rating": _F, "fmt": _S, "status": _S,
        "notes": _L, "quotes": _L, "started_at": _T}),
    Kind("habits", LIST, "العادات", "Habits", "repeat", {"archived": _B}),
    Kind("plans", LIST, "الخطط", "Plans", "lightbulb", {
        "status": _S, "points": _L, "plan_text": _S, "summary": _S,
        "started_at": _T}),
    Kind("project:", LIST, "مشروع", "Project", "folder"),

    # ── SCHEDULES (sandy_schedules) ──────────────────────────────────────────
    Kind("reminder", SCHEDULE, "تذكير", "Reminder", "bell", {
        "note": _S, "linked_task_id": _S, "parent_summary": _S,
        "source_kind": _S, "series_at": _T, "sent_at": _T, "last_error": _S}),
    Kind("message_to_future_self", SCHEDULE, "رسالة للمستقبل",
         "Message to future self", "envelope", {
             "encrypted": _B, "delivered_at": _T}),
    Kind("scene", SCHEDULE, "مؤقّت مشهد", "Scene timer", "timer", {
        "device": _S, "value": _S, "tries": _I}),
    Kind("daily_nudge", SCHEDULE, "لفتة يومية", "Daily nudge", "sun.max", {
        "nudge_kind": _S, "qid": _S, "date": _S}),
    Kind("summary_nudge", SCHEDULE, "تذكير بالملخص", "Summary nudge",
         "doc.text"),
)

_BY_KEY: Dict[Tuple[str, str], Kind] = {(k.block, k.name): k for k in KINDS}


def names(block: str) -> Tuple[str, ...]:
    return tuple(k.name for k in KINDS if k.block == block)


def get_kind(block: str, name: str) -> Optional[Kind]:
    row = _BY_KEY.get((block, name))
    if row is not None:
        return row
    if _PREFIX_MARK in name:
        prefix, _, rest = name.partition(_PREFIX_MARK)
        if rest:
            return _BY_KEY.get((block, prefix + _PREFIX_MARK))
    return None


def _type_ok(value: Any, expected: Any) -> bool:
    if value is None:
        return True
    # bool is an int subclass; a True must not pass as a count.
    if isinstance(value, bool):
        return expected is bool
    if expected is float:
        return isinstance(value, (int, float))
    return isinstance(value, expected)


def validate(block: str, name: str, data: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The kind's ``data`` as a plain dict, or KindError."""
    row = get_kind(block, name)
    if row is None or row.name.endswith(_PREFIX_MARK) and name == row.name:
        raise KindError(f"unknown {block} kind {name!r}")
    out = dict(data or {})
    for key, value in out.items():
        if key not in row.fields:
            raise KindError(f"{name!r} has no data field {key!r}")
        if not _type_ok(value, row.fields[key]):
            raise KindError(
                f"{name!r}.{key} must be {row.fields[key].__name__}, "
                f"got {type(value).__name__}")
    return out
