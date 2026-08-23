"""Everything the owner has told Sandy, in one short block.

**The gap this closes.** Every list in the app — tasks, reminders, habits,
books, goals, expenses, shopping, journal — has a tool that reads it *when
asked*. So "what's on my list?" works. But "what do you think I'll be doing next
year?" does not: nothing in that question names a tool, so she answers from
personality alone and sounds like she has never met him.

The owner put it exactly right: he adds a book, a habit, a goal — and expects
her to be **aware** of it, not merely able to look it up. Awareness is what you
know without being asked.

**Why it is a summary and not the data.** A prompt has a budget, and his lists
grow forever. Twelve books and thirty tasks would push out the conversation
itself. So each area contributes a line or two: counts, the current few, the
streaks that are alive. Enough for her to reason from and to know what to ask
about — the tools are still there for detail.

**Deliberately generic.** Adding a feature should not require editing this file
to make her aware of it: every area is read through the same shape, so a new
list joins the block by existing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Keep it tight. This rides in every prompt, and a block nobody reads to the end
# is worse than a short one — the model weights the start heaviest.
_MAX_ITEMS = 4
_MAX_CHARS = 900


def _line(label: str, items: List[str], total: Optional[int] = None) -> str:
    if not items:
        return ""
    head = "، ".join(items[:_MAX_ITEMS])
    if total and total > len(items[:_MAX_ITEMS]):
        head += f" (وغيرها — {total} بالمجموع)"
    return f"{label}: {head}"


def _safe(fn: Callable[[], Any], what: str) -> Any:
    """Run one reader. A broken area must not blank the whole picture.

    Each of these touches a different store, and any of them can be empty,
    missing, or mid-migration. Losing one line is a small loss; losing the block
    because a single list misbehaved is the failure this guards against.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[life] %s unavailable: %s", what, exc)
        return None


def build_life_snapshot() -> str:
    """One block describing the owner's current life, or "" if there is none.

    Runs inside the caller's tenant context — every store below is scoped, so
    this can only ever see the person who is asking.
    """
    parts: List[str] = []

    tasks = _safe(lambda: __import__(
        "app.features.tasks_store", fromlist=["x"]).load_tasks(), "tasks")
    if tasks:
        open_tasks = [t for t in tasks if not t.get("done")]
        parts.append(_line("مهامه المفتوحة",
                           [str(t.get("text", ""))[:60] for t in open_tasks],
                           len(open_tasks)))

    rem = _safe(lambda: __import__(
        "app.features.reminders_store", fromlist=["x"]).load_reminders(), "reminders")
    if rem:
        parts.append(_line("تذكيراته",
                           [str(r.get("text", ""))[:60] for r in rem], len(rem)))

    habits = _safe(lambda: __import__(
        "app.features.habits_store", fromlist=["x"]).list_habits(), "habits")
    if habits:
        parts.append(_line("عاداته", [
            f"{h.get('name','')} ({h.get('streak',0)} يوم)" for h in habits
        ], len(habits)))

    books = _safe(lambda: __import__(
        "app.features.reading_store", fromlist=["x"]).list_books(), "books")
    if books:
        reading = [b for b in books if str(b.get("status", "")) == "reading"]
        parts.append(_line("بيقرا", [str(b.get("title", ""))[:50] for b in reading],
                           len(reading)) or
                     _line("كتبه", [str(b.get("title", ""))[:50] for b in books],
                           len(books)))

    shopping = _safe(lambda: __import__(
        "app.features.shopping_store", fromlist=["x"]).list_items(), "shopping")
    if shopping:
        pending = [s for s in shopping if not s.get("done")]
        parts.append(_line("قائمة تسوّقه",
                           [str(s.get("item", ""))[:40] for s in pending], len(pending)))

    if not parts:
        return ""

    body = "\n".join(p for p in parts if p)[:_MAX_CHARS]
    # Framed as background, not as a request. Without this the model has been
    # known to answer the *contents* — reading a task list aloud when the owner
    # only said hello.
    return ("\n[حياته الحالية — خلفية للاطّلاع، مش طلب منه هلّق:\n"
            f"{body}\n"
            "استعمليها لتفهمي سياقه وتربطي كلامه بحياته. لا تعدّديها إلا إذا سأل.]")


# ── البحث بكل إشي ────────────────────────────────────────────────────────────
#
# اللقطة فوق بتعطي **الشكل**: كم مهمة، شو أحدث كتاب، أي عادة صامدة. وهاد مفيد
# وما بيكفي — أربعة عناصر مش «كل إشي»، وصاحبها محقّ.
#
# بس حشر كل إشي بكل رسالة مش الحلّ التاني: مية مهمة وخمسين كتاب وسنة يوميات
# بتزاحم المحادثة نفسها، وبتخلّي النموذج يضيع بين ما ما إله علاقة.
#
# فالطبقة التانية عكسها: **ما بنحمل كل إشي — بنجيب المتعلّق بالسؤال.** بيسأل
# عن كتاب، بيوصلها كل كتبه اللي فيها الكلمة؛ بيسأل عن مصروف، بتوصلها مصاريفه.
# مجموع الطبقتين إنها بتعرف حياته بالشكل، وبتوصل لأي تفصيل لحظة ما يلزم.
#
# بحث نصّي مباشر مش تضمينات: القوائم قصيرة والمطابقة بالكلمة كافية، وما بده
# نداء خارجي ولا كلفة ولا انتظار.

_STOP = {"شو", "كيف", "ليش", "وين", "إيمتى", "مين", "هل", "في", "من", "على",
         "عن", "الي", "اللي", "انا", "أنا", "بدي", "بدّي", "لو", "كان", "يكون",
         "what", "how", "why", "when", "who", "the", "a", "is", "my", "me"}


def index_life_for_search() -> int:
    """اكتب عناصر حياته بمخزن البحث بالمعنى. بترجّع كم عنصر انفهرس.

    **ليش هاي أهم من البحث بالكلمة اللي تحت.**

    مطابقة الكلمة بتفشل بالمكان اللي بتلزم فيه: بتسأل عن «الرياضة» وعادتك اسمها
    «الجيم» — نفس الشي عندك، وحرفان مختلفان عند الحاسوب. وبتسأل «شو بتتوقّعي
    أكون السنة الجاي» وما في ولا كلمة تطابق إشي، مع إنّ الجواب كله بأهدافك
    وكتبك.

    والبحث بالمعنى بيحلّها: العنصر بينتحوّل لتمثيل رقمي بيقيس **المعنى**، فسؤال
    عن الرياضة بيلاقي الجيم، وسؤال عن المستقبل بيلاقي الأهداف.

    والآلية موجودة عندنا من زمان (`semantic_memory`) — بس كانت شغّالة ع
    المحادثات وحقائق متفرّقة، **ومش شايفة قوائمه أبدًا**. فكانت ساندي بتلاقي
    بالمعنى إشي قالها إياه مرّة بالحكي، وما بتلاقي كتابًا مسجّلًا عندها بالاسم.

    بينادى بعد أي تعديل ع القوائم، وبيتخطّى اللي انفهرس قبل — فالكلفة مرّة
    لكل عنصر مش مع كل سؤال.
    """
    from app.agent.semantic_memory import load_facts_to_chroma

    facts: List[Dict[str, str]] = []

    def add(items: Any, fields: List[str], kind: str, prefix: str) -> None:
        for it in (items or []):
            text = " · ".join(str(it.get(f, "")) for f in fields if it.get(f))
            if text.strip():
                facts.append({"text": f"{prefix}: {text}"[:300], "type": kind})

    add(_safe(lambda: __import__("app.features.reading_store", fromlist=["x"])
              .list_books(), "books"), ["title", "author", "category"], "book", "كتاب عنده")
    add(_safe(lambda: __import__("app.features.habits_store", fromlist=["x"])
              .list_habits(), "habits"), ["name"], "habit", "عادة بيتابعها")
    add(_safe(lambda: __import__("app.features.tasks_store", fromlist=["x"])
              .load_tasks(), "tasks"), ["text", "notes"], "task", "مهمة عنده")
    add(_safe(lambda: __import__("app.features.journal_store", fromlist=["x"])
              .recent_entries(limit=100), "journal"), ["text"], "journal", "دوّن")

    if not facts:
        return 0
    _safe(lambda: load_facts_to_chroma(facts), "index")
    return len(facts)


def _terms(query: str) -> List[str]:
    words = [w.strip("؟?.,!،:؛\"'") for w in (query or "").split()]
    return [w for w in words if len(w) >= 3 and w not in _STOP][:6]


def search_life(query: str) -> str:
    """كل إشي مرتبط بسؤاله، من كل قوائمه. فاضي لو ما في علاقة.

    بتنادى بكل دور مع نصّ رسالته.
    """
    terms = _terms(query)
    if not terms:
        return ""

    hits: List[str] = []

    def scan(items: Any, fields: List[str], label: str) -> None:
        if not items:
            return
        for it in items:
            blob = " ".join(str(it.get(f, "")) for f in fields).lower()
            if any(t.lower() in blob for t in terms):
                text = " · ".join(str(it.get(f, "")) for f in fields if it.get(f))
                hits.append(f"{label}: {text[:110]}")

    scan(_safe(lambda: __import__("app.features.reading_store", fromlist=["x"])
               .list_books(), "books"), ["title", "author", "category"], "كتاب")
    scan(_safe(lambda: __import__("app.features.tasks_store", fromlist=["x"])
               .load_tasks(), "tasks"), ["text", "notes"], "مهمة")
    scan(_safe(lambda: __import__("app.features.journal_store", fromlist=["x"])
               .recent_entries(limit=200), "journal"), ["text"], "يومية")
    scan(_safe(lambda: __import__("app.features.habits_store", fromlist=["x"])
               .list_habits(), "habits"), ["name"], "عادة")
    scan(_safe(lambda: __import__("app.features.reminders_store", fromlist=["x"])
               .load_reminders(), "reminders"), ["text"], "تذكير")

    if not hits:
        return ""
    return ("\n[من سجلّاته، مرتبط بسؤاله:\n" + "\n".join(hits[:12])[:1200] + "]")
