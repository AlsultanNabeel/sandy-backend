"""books tools."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def book_add(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import add_book

    r = add_book(
        str(args.get("title", "")),
        status=str(args.get("status", "reading")),
        total_pages=int(args.get("total_pages", 0) or 0),
        cover_url=str(args.get("cover_url", "")),
        current_page=int(args.get("current_page", 0) or 0),
        author=str(args.get("author", "")),
        category=str(args.get("category", "")),
        fmt=str(args.get("fmt", "")),
    )
    if r.get("ok"):
        by = f" لـ{args.get('author')}" if args.get("author") else ""
        return {"handled": True, "reply": f"📚 سجلت كتاب «{r['title']}»{by}."}
    if r.get("error") == "exists":
        return {"handled": True, "reply": "هالكتاب مسجل أصلاً 📚"}
    return {"handled": True, "reply": "شو اسم الكتاب؟"}


def book_list(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import list_books

    status = str(args.get("status", "")).strip()
    books = list_books(status=status)
    if not books:
        return {"handled": True, "reply": "ما في كتب مسجلة 📚"}
    label = {"reading": "📖", "done": "✅", "wishlist": "🔖"}
    lines = []
    for b in books:
        prog = ""
        if b["total_pages"]:
            prog = f" — صفحة {b['current_page']} من {b['total_pages']}"
        elif b["current_page"]:
            prog = f" — صفحة {b['current_page']}"
        by = f" · {b['author']}" if b.get("author") else ""
        stars = " " + "⭐" * b["rating"] if b.get("rating") else ""
        lines.append(f"{label.get(b['status'], '📚')} {b['title']}{by}{prog}{stars}")
    return {"handled": True, "reply": "📚 كتبك:\n" + "\n".join(lines)}


def book_status(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import set_book_status

    r = set_book_status(str(args.get("title", "")), str(args.get("status", "")))
    if r.get("ok"):
        s = str(args.get("status", ""))
        word = {"done": "مكتمل 🎉", "reading": "قيد القراءة 📖", "wishlist": "عالقائمة 🔖"}.get(s, s)
        return {"handled": True, "reply": f"«{r['title']}» صار {word}"}
    return {"handled": True, "reply": "ما لقيت الكتاب أو الحالة غير صالحة."}


def book_meta(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import set_book_meta

    def _opt(k, cast=str):
        v = args.get(k)
        return cast(v) if v is not None and str(v) != "" else None

    r = set_book_meta(
        str(args.get("title", "")),
        author=_opt("author"),
        category=_opt("category"),
        rating=_opt("rating", int),
        fmt=_opt("fmt"),
        total_pages=_opt("total_pages", int),
        current_page=_opt("current_page", int),
    )
    if not r.get("ok"):
        return {"handled": True, "reply": "ما لقيت الكتاب أو ما في إشي أعدّله."}
    return {"handled": True, "reply": f"✏️ حدّثت «{r['title']}»."}


def book_note(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import add_note

    r = add_note(str(args.get("title", "")), str(args.get("text", "")))
    if not r.get("ok"):
        return {"handled": True, "reply": "ما لقيت الكتاب أو الملاحظة فاضية."}
    return {"handled": True, "reply": f"📝 ضفت ملاحظة على «{r['title']}»."}


def book_quote(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import add_quote

    r = add_quote(str(args.get("title", "")), str(args.get("text", "")), page=int(args.get("page", 0) or 0))
    if not r.get("ok"):
        return {"handled": True, "reply": "ما لقيت الكتاب أو الاقتباس فاضي."}
    return {"handled": True, "reply": f"❝ حفظت اقتباس من «{r['title']}»."}


def reading_goal(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import goal_progress, set_reading_goal

    if args.get("books_year") is not None or args.get("pages_year") is not None:
        r = set_reading_goal(
            books_year=int(args.get("books_year", 0) or 0),
            pages_year=int(args.get("pages_year", 0) or 0),
        )
        parts = []
        if r["books_year"]:
            parts.append(f"{r['books_year']} كتاب")
        if r["pages_year"]:
            parts.append(f"{r['pages_year']} صفحة")
        return {"handled": True, "reply": "🎯 ظبّطت هدف السنة: " + " و".join(parts) + "."}
    p = goal_progress()
    if not p["books_year"] and not p["pages_year"]:
        return {"handled": True, "reply": "ما في هدف قراءة محدد — قول مثلاً «هدفي ٢٤ كتاب بالسنة»."}
    bits = []
    if p["books_year"]:
        bits.append(f"📚 {p['books_done']}/{p['books_year']} كتاب")
    if p["pages_year"]:
        bits.append(f"📄 {p['pages_read']}/{p['pages_year']} صفحة")
    return {"handled": True, "reply": "🎯 هدف السنة: " + " · ".join(bits)}


def reading_start(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import start_session

    r = start_session(str(args.get("title", "")))
    if r.get("ok"):
        return {
            "handled": True,
            "reply": f"📖 بلشنا — «{r['title']}» من صفحة {r['start_page']}. قراءة ممتعة! "
                     f"(قول «توقف مؤقت» للاستراحة أو «وقفت» للإنهاء)",
        }
    if r.get("error") == "already_active":
        return {"handled": True, "reply": "في جلسة قراءة شغالة أصلاً — قول «وقفت» لتسكيرها أول."}
    return {"handled": True, "reply": "شو الكتاب اللي بدك تقراه؟ (سمّيه وأنا بسجله)"}


def reading_pause(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import pause_session, resume_session

    if args.get("resume"):
        r = resume_session()
        if r.get("ok"):
            return {"handled": True, "reply": "📖 رجعنا — كمل قراءة!"}
        return {"handled": True, "reply": "ما في جلسة موقوفة مؤقتاً."}
    r = pause_session()
    if r.get("ok"):
        return {"handled": True, "reply": "⏸ وقفت العداد — قول «كمل قراءة» لما ترجع."}
    if r.get("error") == "already_paused":
        return {"handled": True, "reply": "هي أصلاً موقوفة مؤقتاً ⏸"}
    return {"handled": True, "reply": "ما في جلسة قراءة شغالة."}


def reading_stop(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.reading_store import stop_session

    page = args.get("page")
    r = stop_session(end_page=int(page) if page is not None else None)
    if not r.get("ok"):
        return {"handled": True, "reply": "ما في جلسة قراءة شغالة."}
    if r.get("needs_page"):
        return {"handled": True, "reply": "وين وصلت؟ قلي رقم الصفحة 📖"}
    msg = f"📖 سكّرت الجلسة — قريت {r['pages']} صفحة بـ {r['minutes']} دقيقة."
    if r.get("finished_book"):
        msg += f"\n🎉🎉 وخلّصت «{r['title']}» كله — مبرووك!"
    elif r.get("total_pages"):
        msg += f"\nوصلت صفحة {r['current_page']} من {r['total_pages']}."
    return {"handled": True, "reply": msg}


# ── التركيز ──────────────────────────────────────────────────────────────────
