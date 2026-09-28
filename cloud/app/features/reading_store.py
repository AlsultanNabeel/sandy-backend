"""وضع القراءة: كتب (sandy_books)، جلسات (sandy_reading_sessions)، وهدف سنوي (sandy_reading_meta).

الدورة: «بديت أقرا» → جلسة نشطة (وحدة بس) → «توقف مؤقت» / «كمل» → «وقفت»
بيسأل «وين وصلت؟» وبيحدّث الكتاب. مفتاح الهدف فيه معرّف المستأجر.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.utils.tenant_db import scoped
from app.utils.text_query import contains, equals
from app.utils.time import USER_TZ
from app.utils.user_profiles import current_user_id
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_BOOKS = "sandy_books"
_SESS = "sandy_reading_sessions"
_META = "sandy_reading_meta"
_FORMATS = {"paper", "ebook", "audio"}


def init_reading_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_SESS].create_index(
            [("user_id", 1), ("state", 1), ("started_at", -1)], background=True
        )
        mongo_db[_BOOKS].create_index(
            [("user_id", 1), ("status", 1), ("created_at", -1)], background=True
        )
        logger.info("[ReadingStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ReadingStore] index skipped: {e}")


def _books():
    return scoped(get_db(), _BOOKS)


def _sess():
    return scoped(get_db(), _SESS)


def _meta():
    return scoped(get_db(), _META)


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _find_book(title: str) -> Optional[Dict[str, Any]]:
    tl = str(title or "").strip()
    coll = _books()
    if not tl or coll is None:
        return None
    # تطابق كامل أول، بعدين احتواء.
    exact = coll.find_one(equals("title", tl))
    if exact is not None:
        return exact
    return coll.find_one(contains("title", tl))


# ─── الكتب ───────────────────────────────────────────────────────────────────

def add_book(
    title: str,
    status: str = "reading",
    total_pages: int = 0,
    cover_url: str = "",
    current_page: int = 0,
    author: str = "",
    category: str = "",
    fmt: str = "",
) -> Dict[str, Any]:
    coll = _books()
    if coll is None:
        return {"ok": False, "error": "unauthorized"}
    title = str(title or "").strip()
    if not title:
        return {"ok": False, "error": "empty_title"}
    existing = _find_book(title)
    if existing and (existing.get("title", "") or "").strip().lower() == title.lower():
        return {"ok": False, "error": "exists"}
    status = status if status in {"reading", "done", "wishlist"} else "reading"
    fmt = fmt if fmt in _FORMATS else ""
    doc = {
        "_id": uuid.uuid4().hex,
        "title": title,
        "author": str(author or "").strip(),
        "category": str(category or "").strip(),
        "cover_url": str(cover_url or "").strip(),
        "total_pages": max(0, int(total_pages or 0)),
        "current_page": max(0, int(current_page or 0)),
        "rating": 0,
        "fmt": fmt,
        "status": status,
        "notes": [],
        "quotes": [],
        "started_at": _now() if status == "reading" else None,
        "created_at": _now(),
        "finished_at": _now() if status == "done" else None,
    }
    coll.insert_one(doc)
    return {"ok": True, "id": doc["_id"], "title": title}


def set_book_meta(
    title: str,
    author: Optional[str] = None,
    category: Optional[str] = None,
    rating: Optional[int] = None,
    fmt: Optional[str] = None,
    total_pages: Optional[int] = None,
    current_page: Optional[int] = None,
) -> Dict[str, Any]:
    """تحديث جزئي — أي حقل None بينحفظ زي ما هو."""
    coll = _books()
    if coll is None:
        return {"ok": False, "error": "unauthorized"}
    b = _find_book(title)
    if not b:
        return {"ok": False, "error": "not_found"}
    updates: Dict[str, Any] = {}
    if author is not None:
        updates["author"] = str(author).strip()
    if category is not None:
        updates["category"] = str(category).strip()
    if rating is not None:
        updates["rating"] = max(0, min(5, int(rating)))
    if fmt is not None:
        updates["fmt"] = fmt if fmt in _FORMATS else ""
    if total_pages is not None:
        updates["total_pages"] = max(0, int(total_pages))
    if current_page is not None:
        updates["current_page"] = max(0, int(current_page))
    if not updates:
        return {"ok": False, "error": "nothing_to_update"}
    coll.update_one({"_id": b["_id"]}, {"$set": updates})
    return {"ok": True, "title": b.get("title", ""), "updated": list(updates)}


def add_note(title: str, text: str) -> Dict[str, Any]:
    """ملاحظة حرة على كتاب."""
    coll = _books()
    if coll is None:
        return {"ok": False}
    b = _find_book(title)
    text = str(text or "").strip()
    if not b or not text:
        return {"ok": False}
    coll.update_one(
        {"_id": b["_id"]},
        {"$push": {"notes": {"text": text, "at": _now()}}},
    )
    return {"ok": True, "title": b.get("title", "")}


def add_quote(title: str, text: str, page: int = 0) -> Dict[str, Any]:
    """اقتباس من كتاب، مع رقم صفحة اختياري."""
    coll = _books()
    if coll is None:
        return {"ok": False}
    b = _find_book(title)
    text = str(text or "").strip()
    if not b or not text:
        return {"ok": False}
    coll.update_one(
        {"_id": b["_id"]},
        {"$push": {"quotes": {"text": text, "page": max(0, int(page or 0)), "at": _now()}}},
    )
    return {"ok": True, "title": b.get("title", "")}


def set_book_status(title: str, status: str) -> Dict[str, Any]:
    coll = _books()
    if coll is None:
        return {"ok": False}
    b = _find_book(title)
    if not b or status not in {"reading", "done", "wishlist"}:
        return {"ok": False}
    updates: Dict[str, Any] = {"status": status}
    if status == "done":
        updates["finished_at"] = _now()
        if b.get("total_pages"):
            updates["current_page"] = b["total_pages"]
    elif status == "reading" and not b.get("started_at"):
        updates["started_at"] = _now()
    coll.update_one({"_id": b["_id"]}, {"$set": updates})
    return {"ok": True, "title": b.get("title", "")}


def list_books(status: str = "") -> List[Dict[str, Any]]:
    coll = _books()
    if coll is None:
        return []
    q: Dict[str, Any] = {}
    if status in {"reading", "done", "wishlist"}:
        q["status"] = status
    # Counts computed in the database; the note/quote arrays are most of the document.
    pipeline = [
        {"$match": q},
        {"$sort": {"created_at": -1}},
        {"$limit": 100},
        {"$project": {
            "title": 1, "author": 1, "category": 1, "cover_url": 1, "status": 1,
            "total_pages": 1, "current_page": 1, "rating": 1, "fmt": 1,
            "notes_count": {"$size": {"$ifNull": ["$notes", []]}},
            "quotes_count": {"$size": {"$ifNull": ["$quotes", []]}},
        }},
    ]
    return [
        {
            "id": d["_id"],
            "title": d.get("title", ""),
            "author": d.get("author", ""),
            "category": d.get("category", ""),
            "cover_url": d.get("cover_url", ""),
            "status": d.get("status", "reading"),
            "total_pages": d.get("total_pages", 0),
            "current_page": d.get("current_page", 0),
            "rating": d.get("rating", 0),
            "fmt": d.get("fmt", ""),
            "notes_count": d.get("notes_count", 0),
            "quotes_count": d.get("quotes_count", 0),
        }
        for d in coll.aggregate(pipeline)
    ]


# ─── الجلسات ─────────────────────────────────────────────────────────────────

def active_session() -> Optional[Dict[str, Any]]:
    sess = _sess()
    if sess is None:
        return None
    return sess.find_one({"state": {"$in": ["active", "paused"]}})


def start_session(title: str = "") -> Dict[str, Any]:
    """«بديت أقرا» — يفتح جلسة عالكتاب المسمّى أو آخر كتاب قيد القراءة."""
    books = _books()
    sess = _sess()
    if books is None or sess is None:
        return {"ok": False, "error": "unauthorized"}
    if active_session():
        return {"ok": False, "error": "already_active"}

    book = _find_book(title) if title else None
    if book is None:
        reading = list_books(status="reading")
        if title and not book:
            r = add_book(title, status="reading")
            if not r.get("ok"):
                return {"ok": False, "error": "no_book"}
            book = books.find_one({"_id": r["id"]})
        elif reading:
            book = books.find_one({"_id": reading[0]["id"]})
        else:
            return {"ok": False, "error": "no_book"}

    if book.get("status") != "reading":
        books.update_one({"_id": book["_id"]}, {"$set": {"status": "reading"}})

    session = {
        "_id": uuid.uuid4().hex,
        "book_id": book["_id"],
        "started_at": _now(),
        "ended_at": None,
        "paused_at": None,
        "paused_total_sec": 0,
        "start_page": int(book.get("current_page", 0) or 0),
        "end_page": None,
        "state": "active",
    }
    sess.insert_one(session)
    return {
        "ok": True,
        "title": book.get("title", ""),
        "start_page": session["start_page"],
    }


def pause_session() -> Dict[str, Any]:
    """«توقف مؤقت» — يجمّد عداد الوقت بدون إغلاق الجلسة."""
    sess = _sess()
    if sess is None:
        return {"ok": False, "error": "unauthorized"}
    s = active_session()
    if not s:
        return {"ok": False, "error": "no_session"}
    if s["state"] == "paused":
        return {"ok": False, "error": "already_paused"}
    sess.update_one(
        {"_id": s["_id"]},
        {"$set": {"state": "paused", "paused_at": _now()}},
    )
    return {"ok": True}


def resume_session() -> Dict[str, Any]:
    """«كمل قراءة» — يرجّع العداد بعد التوقف المؤقت."""
    sess = _sess()
    if sess is None:
        return {"ok": False, "error": "unauthorized"}
    s = active_session()
    if not s or s["state"] != "paused":
        return {"ok": False, "error": "not_paused"}
    paused_sec = 0
    pa = _aware(s.get("paused_at"))
    if pa:
        paused_sec = int((_now() - pa).total_seconds())
    sess.update_one(
        {"_id": s["_id"]},
        {
            "$set": {"state": "active", "paused_at": None},
            "$inc": {"paused_total_sec": paused_sec},
        },
    )
    return {"ok": True}


def stop_session(end_page: Optional[int] = None) -> Dict[str, Any]:
    """«وقفت» — يسكّر الجلسة؛ بلا end_page بيرجّع needs_page=True (ساندي بتسأل «وين وصلت؟»)."""
    books = _books()
    sess = _sess()
    if books is None or sess is None:
        return {"ok": False, "error": "unauthorized"}
    s = active_session()
    if not s:
        return {"ok": False, "error": "no_session"}
    if end_page is None:
        return {"ok": True, "needs_page": True}

    end_page = max(0, int(end_page))
    now = _now()
    paused_sec = int(s.get("paused_total_sec", 0) or 0)
    pa = _aware(s.get("paused_at"))
    if s["state"] == "paused" and pa:
        paused_sec += int((now - pa).total_seconds())
    started = _aware(s["started_at"])
    duration_min = max(0, int(((now - started).total_seconds() - paused_sec) / 60))
    pages = max(0, end_page - int(s.get("start_page", 0) or 0))

    sess.update_one(
        {"_id": s["_id"]},
        {
            "$set": {
                "state": "done",
                "ended_at": now,
                "end_page": end_page,
                "paused_total_sec": paused_sec,
            }
        },
    )

    book = books.find_one({"_id": s["book_id"]}) or {}
    updates: Dict[str, Any] = {"current_page": end_page}
    finished = bool(book.get("total_pages")) and end_page >= book["total_pages"]
    if finished:
        updates["status"] = "done"
        updates["finished_at"] = now
    books.update_one({"_id": s["book_id"]}, {"$set": updates})

    return {
        "ok": True,
        "title": book.get("title", ""),
        "pages": pages,
        "minutes": duration_min,
        "current_page": end_page,
        "total_pages": book.get("total_pages", 0),
        "finished_book": finished,
    }


# Covers a year of streak and "since January 1st", so one read serves both.
_STREAK_WINDOW_DAYS = 400

_SESSION_FIELDS = {"start_page": 1, "end_page": 1, "started_at": 1,
                   "ended_at": 1, "paused_total_sec": 1}


def _done_sessions(since: datetime) -> List[Dict[str, Any]]:
    sess = _sess()
    if sess is None:
        return []
    # بلا .limit() بالقصد: سقف ع مجموع بيرجّع رقم أصغر من الحقيقة. المدى محدود بالتاريخ.
    return list(sess.find({"state": "done", "ended_at": {"$gte": since}}, _SESSION_FIELDS))


def _year_start() -> datetime:
    now_local = _now().astimezone(USER_TZ)
    return datetime(now_local.year, 1, 1, tzinfo=USER_TZ).astimezone(timezone.utc)


def _session_pages(s: Dict[str, Any]) -> int:
    return max(0, int(s.get("end_page", 0) or 0) - int(s.get("start_page", 0) or 0))


def reading_stats(days: int = 30,
                  rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """{sessions, pages, minutes, pages_per_day, streak_days} عبر فترة.

    ``rows``: pre-fetched finished sessions covering the streak window (see reading_overview).
    """
    empty = {"sessions": 0, "pages": 0, "minutes": 0, "pages_per_day": 0, "streak_days": 0}
    if _sess() is None:
        return empty
    now = _now()
    since = now - timedelta(days=max(1, days))
    if rows is None:
        rows = _done_sessions(min(since, now - timedelta(days=_STREAK_WINDOW_DAYS)))
    sessions = pages = minutes = 0
    active_dates = set()
    all_dates = set()
    for s in rows:
        st, en = _aware(s.get("started_at")), _aware(s.get("ended_at"))
        if en:
            all_dates.add(en.astimezone(USER_TZ).date())
        if not en or en < since:
            continue
        sessions += 1
        pages += _session_pages(s)
        active_dates.add(en.astimezone(USER_TZ).date())
        if st:
            minutes += max(
                0, int(((en - st).total_seconds() - int(s.get("paused_total_sec", 0) or 0)) / 60)
            )
    return {
        "sessions": sessions,
        "pages": pages,
        "minutes": minutes,
        "pages_per_day": round(pages / len(active_dates)) if active_dates else 0,
        "streak_days": _streak_from_days(all_dates),
    }


def _streak_from_days(days_set: set) -> int:
    """عدد الأيام المتتالية (تنتهي اليوم أو أمس) اللي فيها جلسة قراءة منجزة."""
    if not days_set:
        return 0
    today = _now().astimezone(USER_TZ).date()
    if today not in days_set and (today - timedelta(days=1)) not in days_set:
        return 0
    cur = today if today in days_set else today - timedelta(days=1)
    streak = 0
    while cur in days_set:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def reading_overview(days: int = 30) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """``(reading_stats(days), goal_progress())`` from one sessions read."""

    now = _now()
    since = min(now - timedelta(days=max(1, days)),
                now - timedelta(days=_STREAK_WINDOW_DAYS),
                _year_start())
    rows = _done_sessions(since)
    return reading_stats(days, rows=rows), goal_progress(rows=rows)


def set_reading_goal(books_year: Optional[int] = None,
                     pages_year: Optional[int] = None) -> Dict[str, Any]:
    """هدف القراءة السنوي (كتب و/أو صفحات)؛ بس الأجزاء المعطاة بتتغيّر."""
    uid = current_user_id()
    if uid is None:
        return {"ok": False}
    meta = _meta()
    if meta is None:
        return {"ok": False}
    changes: Dict[str, Any] = {"user_id": uid}
    if books_year is not None:
        changes["books_year"] = max(0, int(books_year))
    if pages_year is not None:
        changes["pages_year"] = max(0, int(pages_year))
    meta.update_one({"_id": f"goal:{uid}"}, {"$set": changes}, upsert=True)
    goal = meta.find_one({"_id": f"goal:{uid}"}) or {}
    return {"ok": True, "books_year": int(goal.get("books_year") or 0),
            "pages_year": int(goal.get("pages_year") or 0)}


def goal_progress(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """تقدّم هدف السنة: كتب منجزة + صفحات مقروءة مقابل الهدف (``rows`` مثل reading_stats)."""
    uid = current_user_id()
    books = _books()
    sess = _sess()
    meta = _meta()
    if uid is None or books is None or sess is None or meta is None:
        return {"books_year": 0, "pages_year": 0, "books_done": 0, "pages_read": 0}
    goal = meta.find_one({"_id": f"goal:{uid}"}) or {}
    year_start = _year_start()
    books_done = books.count_documents(
        {"status": "done", "finished_at": {"$gte": year_start}}
    )
    if rows is None:
        rows = _done_sessions(year_start)
    pages_read = sum(
        _session_pages(s) for s in rows
        if (_aware(s.get("ended_at")) or year_start) >= year_start
    )
    return {
        "books_year": int(goal.get("books_year", 0)),
        "pages_year": int(goal.get("pages_year", 0)),
        "books_done": books_done,
        "pages_read": pages_read,
    }
