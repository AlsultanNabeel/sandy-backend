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
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# The five lists `search_life` scans, held per tenant version.
#
# The search itself depends on what he just said, so its *result* cannot be
# cached — but what it reads cannot change without a write, and a write moves
# the version (`utils/tenant_version.py`). So the scan stays live and the five
# round trips behind it happen once per change instead of once per message.
# That is the whole remaining cost of the block after the persona cache: five
# reads of lists that were identical to last turn.
# Keyed by tenant alone, with the version **inside** the value. Putting the
# version in the key leaves every old version sitting in the dict, and
# `tenant_version.forget()` sends a deleted account's version back to zero —
# which would make a stale entry reachable again on the worker that did not run
# the delete. Overwriting per tenant cannot do that.
_LISTS_CACHE: Dict[str, Tuple[int, Dict[str, Any], float]] = {}
_LISTS_LOCK = threading.Lock()
_LISTS_MAX = 256
_LISTS_MAX_AGE_S = 600.0

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
        # `list_items` returns the name under `text`; this read `item` and got
        # nothing, so the line she carried in every prompt was «قائمة تسوّقه:
        # ، ، ، (وغيرها — ٧ بالمجموع)» — a count with no items, which is worse
        # than leaving the line out.
        parts.append(_line("قائمة تسوّقه",
                           [str(s.get("text", ""))[:40] for s in pending], len(pending)))

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

    # Same lists the search scans, same cache — this runs on the background pool
    # every turn, and reading them again was four round trips per message for
    # data the search had already fetched.
    lists = _searchable_lists()
    add(lists.get("books"), ["title", "author", "category"], "book", "كتاب عنده")
    add(lists.get("habits"), ["name"], "habit", "عادة بيتابعها")
    add(lists.get("tasks"), ["text", "notes"], "task", "مهمة عنده")
    # The shared fetch reads 200 journal entries; the indexer has always taken
    # 100 and keeps taking 100. Embedding the older half would push tasks and
    # books out of the five slots a turn retrieves, and would enlarge the single
    # batched embedding call that returns nothing for everything when it times
    # out — a change to what she recalls, smuggled in as a change to a limit.
    add((lists.get("journal") or [])[:100], ["text"], "journal", "دوّن")

    if not facts:
        return 0
    _safe(lambda: load_facts_to_chroma(facts), "index")
    return len(facts)


def _terms(query: str) -> List[str]:
    words = [w.strip("؟?.,!،:؛\"'") for w in (query or "").split()]
    return [w for w in words if len(w) >= 3 and w not in _STOP][:6]


_SEARCHED: List[Tuple[str, Callable[[], Any], List[str], str]] = [
    ("books", lambda: __import__("app.features.reading_store", fromlist=["x"])
     .list_books(), ["title", "author", "category"], "كتاب"),
    ("tasks", lambda: __import__("app.features.tasks_store", fromlist=["x"])
     .load_tasks(), ["text", "notes"], "مهمة"),
    ("journal", lambda: __import__("app.features.journal_store", fromlist=["x"])
     .recent_entries(limit=200), ["text"], "يومية"),
    ("habits", lambda: __import__("app.features.habits_store", fromlist=["x"])
     .list_habits(), ["name"], "عادة"),
    ("reminders", lambda: __import__("app.features.reminders_store", fromlist=["x"])
     .load_reminders(), ["text"], "تذكير"),
]


def _searchable_lists() -> Dict[str, Any]:
    """The five lists, from cache when the tenant has not written since."""
    from app.utils.tenant_version import version_for
    from app.utils.user_profiles import current_user_id

    tenant = str(current_user_id() or "")
    version = version_for(tenant) if tenant else -1

    now = time.monotonic()
    if version >= 0:
        with _LISTS_LOCK:
            hit = _LISTS_CACHE.get(tenant)
        if hit is not None and hit[0] == version and hit[2] > now:
            return hit[1]

    lists = {name: _safe(fn, name) for name, fn, _f, _l in _SEARCHED}

    # `_safe` returns None for a store that **raised**, and an empty list for a
    # store that is genuinely empty. Only the second is an answer worth keeping:
    # caching a failure would silently drop a whole list out of her awareness
    # until the next write, since a failure moves no version.
    complete = all(v is not None for v in lists.values())

    if version >= 0 and complete:
        with _LISTS_LOCK:
            if len(_LISTS_CACHE) >= _LISTS_MAX:
                _LISTS_CACHE.clear()
            _LISTS_CACHE[tenant] = (version, lists, now + _LISTS_MAX_AGE_S)
    return lists


def clear_lists_cache() -> None:
    """Drop every cached list. Test-only, and used by account deletion."""
    with _LISTS_LOCK:
        _LISTS_CACHE.clear()


def search_life(query: str) -> str:
    """كل إشي مرتبط بسؤاله، من كل قوائمه. فاضي لو ما في علاقة.

    بتنادى بكل دور مع نصّ رسالته — **البحث حيّ، والقراءة مكشّنة.**
    """
    terms = _terms(query)
    if not terms:
        return ""

    hits: List[str] = []
    lists = _searchable_lists()

    for name, _fn, fields, label in _SEARCHED:
        items = lists.get(name)
        if not items:
            continue
        for it in items:
            blob = " ".join(str(it.get(f, "")) for f in fields).lower()
            if any(t.lower() in blob for t in terms):
                text = " · ".join(str(it.get(f, "")) for f in fields if it.get(f))
                hits.append(f"{label}: {text[:110]}")

    if not hits:
        return ""
    return ("\n[من سجلّاته، مرتبط بسؤاله:\n" + "\n".join(hits[:12])[:1200] + "]")
