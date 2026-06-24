"""وضع القراءة — تتبع كامل للكتب والجلسات والصفحات (على طراز Bookly).

Collections:
  sandy_books
    {_id, title, author, category, cover_url, total_pages, current_page,
     rating: 0..5, fmt: "paper"|"ebook"|"audio"|"",
     status: "reading"|"done"|"wishlist",
     notes: [{text, at}], quotes: [{text, page, at}],
     started_at, created_at, finished_at}
  sandy_reading_sessions
    {_id, book_id, started_at, ended_at, paused_at, paused_total_sec,
     start_page, end_page, state: "active"|"paused"|"done"}
  sandy_reading_meta
    {_id: "goal", books_year, pages_year}   # هدف القراءة السنوي

الدورة: «بديت أقرا» → جلسة نشطة (وحدة بس بكل وقت) → «توقف مؤقت» يجمّد
العداد → «كمل» يرجّعه → «وقفت» يسكّر الجلسة ويسأل «وين وصلت؟» — صفحة
التوقف بتحدّث الكتاب وبتنحسب صفحات الجلسة ومدتها.

عزل المستأجرين مفروض من طبقة scoped(): _books()/_sess()/_meta() ترجع None لو ما
في مستأجر. خانة الهدف (goal) بتضمّن معرّف المستأجر في الـ _id، فبنحتاج
current_user_id() لبناء المفتاح فقط — والعزل نفسه من scoped().
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.utils.user_profiles import current_user_id

_BOOKS = "sandy_books"
_SESS = "sandy_reading_sessions"
_META = "sandy_reading_meta"
_FORMATS = {"paper", "ebook", "audio"}
_mongo_db = None


def init_reading_store(mongo_db) -> None:
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_SESS].create_index(
            [("user_id", 1), ("state", 1), ("started_at", -1)], background=True
        )
        mongo_db[_BOOKS].create_index(
            [("user_id", 1), ("status", 1), ("created_at", -1)], background=True
        )
        print("[ReadingStore] ready")
    except Exception as e:  # noqa: BLE001
        print(f"[ReadingStore] index skipped: {e}")


def _books():
    """Tenant-scoped books collection, or None when no db / no active tenant."""
    return scoped(_mongo_db, _BOOKS)


def _sess():
    """Tenant-scoped reading-sessions collection, or None when no db / no tenant."""
    return scoped(_mongo_db, _SESS)


def _meta():
    """Tenant-scoped reading-meta collection, or None when no db / no tenant."""
    return scoped(_mongo_db, _META)


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _find_book(title: str) -> Optional[Dict[str, Any]]:
    tl = str(title or "").strip().lower()
    coll = _books()
    if not tl or coll is None:
        return None
    # تطابق كامل أول، بعدين احتواء
    for d in coll.find({}):
        if (d.get("title", "") or "").strip().lower() == tl:
            return d
    for d in coll.find({}):
        if tl in (d.get("title", "") or "").lower():
            return d
    return None


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
    """تحديث جزئي لميتاداتا الكتاب — أي حقل None بينحفظ زي ما هو."""
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


def set_book_cover(title: str, cover_url: str) -> bool:
    coll = _books()
    if coll is None:
        return False
    b = _find_book(title)
    if not b:
        return False
    coll.update_one(
        {"_id": b["_id"]},
        {"$set": {"cover_url": str(cover_url or "").strip()}},
    )
    return True


def list_books(status: str = "") -> List[Dict[str, Any]]:
    coll = _books()
    if coll is None:
        return []
    q: Dict[str, Any] = {}
    if status in {"reading", "done", "wishlist"}:
        q["status"] = status
    out = []
    for d in coll.find(q).sort("created_at", -1).limit(100):
        out.append(
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
                "notes_count": len(d.get("notes", [])),
                "quotes_count": len(d.get("quotes", [])),
            }
        )
    return out


def get_book(title: str) -> Optional[Dict[str, Any]]:
    """تفاصيل كتاب كاملة مع الملاحظات والاقتباسات."""
    if _books() is None:
        return None
    d = _find_book(title)
    if not d:
        return None
    return {
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
        "notes": d.get("notes", []),
        "quotes": d.get("quotes", []),
    }


def delete_book(title: str) -> str:
    books = _books()
    sess = _sess()
    if books is None or sess is None:
        return ""
    b = _find_book(title)
    if not b:
        return ""
    sess.delete_many({"book_id": b["_id"]})
    books.delete_one({"_id": b["_id"]})
    return b.get("title", "")


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
            # كتاب جديد بالاسم المعطى — منضيفه قيد القراءة ومنبلش
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
    """«وقفت» — يسكّر الجلسة. لو end_page مش معطى يرجّع needs_page=True
    (ساندي بتسأل «وين وصلت؟») والنداء التالي بمرر الصفحة."""
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


def reading_stats(days: int = 30) -> Dict[str, Any]:
    """{sessions, pages, minutes, pages_per_day, streak_days} عبر فترة."""
    sess = _sess()
    empty = {"sessions": 0, "pages": 0, "minutes": 0, "pages_per_day": 0, "streak_days": 0}
    if sess is None:
        return empty
    from datetime import timedelta

    from app.utils.time import USER_TZ

    since = _now() - timedelta(days=max(1, days))
    sessions = pages = minutes = 0
    active_dates = set()
    for s in sess.find({"state": "done", "ended_at": {"$gte": since}}):
        sessions += 1
        sp, ep = int(s.get("start_page", 0) or 0), int(s.get("end_page", 0) or 0)
        pages += max(0, ep - sp)
        st, en = _aware(s.get("started_at")), _aware(s.get("ended_at"))
        if en:
            active_dates.add(en.astimezone(USER_TZ).date())
        if st and en:
            minutes += max(
                0, int(((en - st).total_seconds() - int(s.get("paused_total_sec", 0) or 0)) / 60)
            )
    return {
        "sessions": sessions,
        "pages": pages,
        "minutes": minutes,
        "pages_per_day": round(pages / len(active_dates)) if active_dates else 0,
        "streak_days": _reading_streak(),
    }


def _reading_streak() -> int:
    """عدد الأيام المتتالية (تنتهي اليوم أو أمس) اللي فيها جلسة قراءة منجزة."""
    sess = _sess()
    if sess is None:
        return 0
    from datetime import timedelta

    from app.utils.time import USER_TZ

    since = _now() - timedelta(days=400)
    days_set = set()
    for s in sess.find(
        {"state": "done", "ended_at": {"$gte": since}}, {"ended_at": 1}
    ):
        en = _aware(s.get("ended_at"))
        if en:
            days_set.add(en.astimezone(USER_TZ).date())
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


def set_reading_goal(books_year: int = 0, pages_year: int = 0) -> Dict[str, Any]:
    """هدف القراءة السنوي — عدد كتب و/أو عدد صفحات."""
    uid = current_user_id()
    if uid is None:
        return {"ok": False}
    meta = _meta()
    if meta is None:
        return {"ok": False}
    by, py = max(0, int(books_year or 0)), max(0, int(pages_year or 0))
    meta.update_one(
        {"_id": f"goal:{uid}"},
        {"$set": {"user_id": uid, "books_year": by, "pages_year": py}},
        upsert=True,
    )
    return {"ok": True, "books_year": by, "pages_year": py}


def goal_progress() -> Dict[str, Any]:
    """تقدّم هدف السنة الحالية: كتب منجزة + صفحات مقروءة مقابل الهدف."""
    uid = current_user_id()
    books = _books()
    sess = _sess()
    meta = _meta()
    if uid is None or books is None or sess is None or meta is None:
        return {"books_year": 0, "pages_year": 0, "books_done": 0, "pages_read": 0}
    from app.utils.time import USER_TZ

    goal = meta.find_one({"_id": f"goal:{uid}"}) or {}
    now_local = _now().astimezone(USER_TZ)
    year_start = datetime(now_local.year, 1, 1, tzinfo=USER_TZ).astimezone(timezone.utc)
    books_done = books.count_documents(
        {"status": "done", "finished_at": {"$gte": year_start}}
    )
    pages_read = 0
    for s in sess.find({"state": "done", "ended_at": {"$gte": year_start}}):
        pages_read += max(0, int(s.get("end_page", 0) or 0) - int(s.get("start_page", 0) or 0))
    return {
        "books_year": int(goal.get("books_year", 0)),
        "pages_year": int(goal.get("pages_year", 0)),
        "books_done": books_done,
        "pages_read": pages_read,
    }
