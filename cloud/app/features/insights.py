"""Weekly insights — the last seven days next to the seven before them.

One read per source, each covering both weeks at once (fourteen days), split
into "this week" / "last week" in memory. The sources are independent, so they
run together through :func:`app.utils.thread_pool.gather`, which carries the
caller's tenant into every job — every collection below is reached through
``scoped()``, never with a hand-written ``user_id`` filter.

Each read is capped (``_CAP``): a summary that has to scan a person's whole
history to say "12 tasks this week" is a bug waiting for a heavy user.

Sandy's sentence about the week is written by the model once per user per ISO
week (and language) and cached in ``sandy_weekly_insights``. The model call has
a hard timeout; on any failure a warm template sentence is returned instead,
and that fallback is cached only briefly so a later open can still get the real
one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.db import get_db
from app.utils.tenant_db import scoped
from app.utils.time import USER_TZ

logger = logging.getLogger(__name__)

CACHE_COLL = "sandy_weekly_insights"

# Most rows any single source read may return.
_CAP = 2000
# Chat threads looked at (each one holds a bounded short-term history).
_STM_THREADS = 20
# The model gets this long, and the wait on it a little more.
_LLM_TIMEOUT_S = 8.0
_LLM_WAIT_S = 10.0
# A template fallback is re-tried after this long instead of sticking all week.
_FALLBACK_TTL = timedelta(hours=1)

# The order the app shows the cards in.
METRIC_KEYS = (
    "tasks_completed", "reminders_done", "focus_minutes", "habit_checkins",
    "expenses_total", "journal_entries", "reading_pages", "reading_sessions",
    "chat_turns",
)


# ── time windows ────────────────────────────────────────────────────────────

class Windows:
    """``[prev_start, cur_start)`` is last week, ``[cur_start, now]`` this week."""

    def __init__(self, now: Optional[datetime] = None):
        self.now = _aware(now) if now else datetime.now(timezone.utc)
        self.cur_start = self.now - timedelta(days=7)
        self.prev_start = self.now - timedelta(days=14)
        today = self.now.astimezone(USER_TZ).date()
        # Day-keyed sources (habit check-ins) use local calendar days: today and
        # the six before it are this week, the seven before those last week.
        self.cur_days = {(today - timedelta(days=i)).isoformat() for i in range(7)}
        self.prev_days = {(today - timedelta(days=i)).isoformat() for i in range(7, 14)}
        self.first_day = (today - timedelta(days=13)).isoformat()

    def bucket(self, when: Any) -> Optional[str]:
        """``"cur"`` / ``"prev"`` / None for a datetime (or ISO string)."""
        dt = _to_dt(when)
        if dt is None or dt > self.now:
            return None
        if dt >= self.cur_start:
            return "cur"
        if dt >= self.prev_start:
            return "prev"
        return None

    def iso_week(self) -> str:
        y, w, _ = self.now.astimezone(USER_TZ).isocalendar()
        return f"{y}-W{w:02d}"


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _to_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return _aware(v)
    if isinstance(v, str) and v:
        try:
            return _aware(datetime.fromisoformat(v.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _pair() -> Dict[str, float]:
    return {"cur": 0, "prev": 0}


def _coll(name: str):
    return scoped(get_db(), name)


# ── one reader per source ───────────────────────────────────────────────────

def _count_by(name: str, field: str, query: Dict[str, Any], w: Windows,
              weight: Optional[Callable[[Dict[str, Any]], float]] = None,
              projection: Optional[Dict[str, int]] = None) -> Dict[str, float]:
    """Sum ``weight(doc)`` (default 1) per window for docs whose ``field`` falls
    in the fourteen days."""
    out = _pair()
    coll = _coll(name)
    if coll is None:
        return out
    q = dict(query)
    q[field] = {"$gte": w.prev_start, "$lte": w.now}
    proj = projection or {field: 1}
    for d in coll.find(q, proj).limit(_CAP):
        b = w.bucket(d.get(field))
        if b:
            out[b] += weight(d) if weight else 1
    return out


def _tasks(w: Windows):
    return _count_by("sandy_tasks", "completed_at", {"done": True}, w)


def _reminders(w: Windows):
    # A reminder whose time came inside the window has been delivered (or is
    # recurring and moved on) — "done" from the person's point of view.
    return _count_by("sandy_reminders", "remind_at", {}, w)


def _focus(w: Windows):
    return _count_by(
        "sandy_focus", "ended_at", {"state": {"$in": ["done", "cancelled"]}}, w,
        weight=lambda d: int(d.get("focused_min") or 0),
        projection={"ended_at": 1, "focused_min": 1},
    )


def _expenses(w: Windows):
    out = _count_by(
        "sandy_expenses", "at", {}, w,
        weight=lambda d: float(d.get("amount") or 0),
        projection={"at": 1, "amount": 1},
    )
    return {k: round(v, 2) for k, v in out.items()}


def _journal(w: Windows):
    return _count_by("sandy_journal", "at", {}, w)


def _reading(w: Windows):
    pages, sessions = _pair(), _pair()
    coll = _coll("sandy_reading_sessions")
    if coll is None:
        return {"pages": pages, "sessions": sessions}
    q = {"state": "done", "ended_at": {"$gte": w.prev_start, "$lte": w.now}}
    proj = {"ended_at": 1, "start_page": 1, "end_page": 1}
    for d in coll.find(q, proj).limit(_CAP):
        b = w.bucket(d.get("ended_at"))
        if not b:
            continue
        sessions[b] += 1
        pages[b] += max(0, int(d.get("end_page") or 0) - int(d.get("start_page") or 0))
    return {"pages": pages, "sessions": sessions}


def _habits(w: Windows):
    checkins = _pair()
    best = 0
    habits = _coll("sandy_habits")
    log = _coll("sandy_habit_log")
    if habits is None or log is None:
        return {"checkins": checkins, "best_streak": 0}
    for d in log.find({"date": {"$gte": w.first_day}}, {"date": 1}).limit(_CAP):
        day = str(d.get("date") or "")
        if day in w.cur_days:
            checkins["cur"] += 1
        elif day in w.prev_days:
            checkins["prev"] += 1
    try:
        from app.features.habits_store import list_habits
        best = max((int(h.get("streak") or 0) for h in list_habits()), default=0)
    except Exception:  # noqa: BLE001 — the streak is a bonus, not the summary
        logger.debug("[insights] streaks unavailable", exc_info=True)
    return {"checkins": checkins, "best_streak": best}


def _chat(w: Windows):
    out = _pair()
    coll = scoped(get_db(), "sandy_stm", bump=False)
    if coll is None:
        return out
    docs = (coll.find({"updated_at": {"$gte": w.prev_start}}, {"history": 1})
            .sort("updated_at", -1).limit(_STM_THREADS))
    for d in docs:
        for m in d.get("history") or []:
            if m.get("role") != "user":
                continue
            b = w.bucket(m.get("timestamp"))
            if b:
                out[b] += 1
    return out


def collect(w: Windows) -> Dict[str, Any]:
    """Every metric for both weeks. Must run inside the caller's tenant."""
    from app.utils.thread_pool import gather

    parts = gather({
        "tasks": lambda: _tasks(w),
        "reminders": lambda: _reminders(w),
        "focus": lambda: _focus(w),
        "expenses": lambda: _expenses(w),
        "journal": lambda: _journal(w),
        "reading": lambda: _reading(w),
        "habits": lambda: _habits(w),
        "chat": lambda: _chat(w),
    })
    reading = parts.get("reading") or {}
    habits = parts.get("habits") or {}
    by_key = {
        "tasks_completed": parts.get("tasks"),
        "reminders_done": parts.get("reminders"),
        "focus_minutes": parts.get("focus"),
        "habit_checkins": habits.get("checkins"),
        "expenses_total": parts.get("expenses"),
        "journal_entries": parts.get("journal"),
        "reading_pages": reading.get("pages"),
        "reading_sessions": reading.get("sessions"),
        "chat_turns": parts.get("chat"),
    }
    metrics = []
    for key in METRIC_KEYS:
        p = by_key.get(key) or _pair()
        cur, prev = p.get("cur", 0), p.get("prev", 0)
        if key != "expenses_total":
            cur, prev = int(cur), int(prev)
        metrics.append({"key": key, "current": cur, "previous": prev})
    return {"metrics": metrics, "best_streak": int(habits.get("best_streak") or 0)}


# ── Sandy's sentence ────────────────────────────────────────────────────────

def _values(metrics: List[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    return {m["key"]: (m["current"], m["previous"]) for m in metrics}


def template_sentence(metrics: List[Dict[str, Any]], lang: str = "ar") -> str:
    """A warm sentence built from the numbers alone — the model-free fallback."""
    v = _values(metrics)
    tasks, prev_tasks = v.get("tasks_completed", (0, 0))
    focus = v.get("focus_minutes", (0, 0))[0]
    active = sum(1 for m in metrics if m["current"])
    if lang == "en":
        if not active:
            return "A quiet week — that's okay. I'm here whenever you want to start again."
        if tasks > prev_tasks:
            return f"You finished {int(tasks)} tasks this week, more than last week. Proud of you!"
        if focus:
            return f"{int(focus)} focused minutes this week — steady steps count. Keep going!"
        return "You showed up this week, and that matters. Let's make the next one a little lighter."
    if not active:
        return "أسبوع هادي، وما في مشكلة. أنا هون وقت ما بدك نرجع نبلّش سوا."
    if tasks > prev_tasks:
        return f"خلّصت {int(tasks)} مهمة هالأسبوع، أكتر من الأسبوع الماضي. فخورة فيك!"
    if focus:
        return f"{int(focus)} دقيقة تركيز هالأسبوع، والخطوات الثابتة بتفرق. كمّل!"
    return "كنت حاضر هالأسبوع وهاد بحد ذاته إنجاز. خلّينا نخلّي الجاي أخف شوي."


_LABELS_AR = {
    "tasks_completed": "مهام منجزة", "reminders_done": "تذكيرات",
    "focus_minutes": "دقائق تركيز", "habit_checkins": "تسجيلات عادات",
    "expenses_total": "مجموع المصاريف", "journal_entries": "تدوينات يوميات",
    "reading_pages": "صفحات قراءة", "reading_sessions": "جلسات قراءة",
    "chat_turns": "رسائل مع ساندي",
}


def _llm_sentence(uid: str, metrics: List[Dict[str, Any]], best_streak: int,
                  lang: str) -> Optional[str]:
    """One or two warm sentences from the model, or None on any failure/timeout."""
    from app.agent.facade import agent as facade
    fn = facade.create_chat_completion
    if fn is None:
        return None
    persona = ""
    try:
        from app.agent.context_builder import build_effective_persona
        persona = build_effective_persona(uid) or ""
    except Exception:  # noqa: BLE001
        logger.debug("[insights] persona unavailable", exc_info=True)
    lines = [f"{_LABELS_AR[m['key']]}: هالأسبوع {m['current']}، الأسبوع الماضي {m['previous']}"
             for m in metrics]
    lines.append(f"أطول سلسلة عادة حالية: {best_streak} يوم")
    language = "English" if lang == "en" else "العربية بلهجة ساندي"
    system = (persona + "\n\nاكتبي جملة أو جملتين دافئتين وقصيرتين عن أسبوع المستخدم "
              "بناءً على الأرقام: احتفلي بالتحسّن، وشجّعي بلطف بلا لوم حيث قلّ. "
              f"بلا قوائم ولا أرقام كثيرة. اللغة: {language}.")

    def _call():
        return fn(messages=[{"role": "system", "content": system},
                            {"role": "user", "content": "\n".join(lines)}],
                  max_tokens=120, timeout=_LLM_TIMEOUT_S)

    from concurrent.futures import TimeoutError as FutTimeout

    from app.utils.thread_pool import sandy_executor
    try:
        result = sandy_executor.submit(_call).result(timeout=_LLM_WAIT_S)
    except FutTimeout:
        logger.warning("[insights] model timed out; using template")
        return None
    except Exception as exc:  # noqa: BLE001 — external call edge
        logger.warning("[insights] model failed; using template: %s", exc)
        return None
    try:
        text = result if isinstance(result, str) else result.choices[0].message.content
    except Exception:  # noqa: BLE001
        return None
    text = (text or "").strip()
    return text[:400] or None


def weekly_sentence(uid: str, metrics: List[Dict[str, Any]], best_streak: int,
                    w: Windows, lang: str = "ar") -> Dict[str, str]:
    """``{"text", "source"}`` — cached per user per ISO week per language."""
    coll = scoped(get_db(), CACHE_COLL, bump=False)
    key = f"{uid}:{w.iso_week()}:{lang}"
    if coll is not None:
        cached = coll.find_one({"_id": key})
        if cached and cached.get("text"):
            fresh = cached.get("source") == "llm" or (
                _to_dt(cached.get("created_at")) or w.prev_start
            ) > datetime.now(timezone.utc) - _FALLBACK_TTL
            if fresh:
                return {"text": cached["text"], "source": cached.get("source", "llm")}

    text = _llm_sentence(uid, metrics, best_streak, lang)
    source = "llm"
    if not text:
        text, source = template_sentence(metrics, lang), "template"

    if coll is not None:
        try:
            coll.update_one(
                {"_id": key},
                {"$set": {"text": text, "source": source,
                          "created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[insights] cache write failed: %s", exc)
    return {"text": text, "source": source}


def weekly_summary(uid: str, lang: str = "ar", now: Optional[datetime] = None) -> Dict[str, Any]:
    """The full payload for ``GET /api/insights/weekly``. Runs in the tenant."""
    w = Windows(now)
    data = collect(w)
    sentence = weekly_sentence(uid, data["metrics"], data["best_streak"], w, lang)
    return {
        "demo": False,
        "week": w.iso_week(),
        "start": w.cur_start.isoformat(),
        "end": w.now.isoformat(),
        "metrics": data["metrics"],
        "best_streak": data["best_streak"],
        "sentence": sentence["text"],
        "sentence_source": sentence["source"],
    }


def demo_summary(lang: str = "ar") -> Dict[str, Any]:
    """Obviously-sample numbers for guests, same shape as the real payload."""
    sample = {
        "tasks_completed": (12, 9), "reminders_done": (7, 8), "focus_minutes": (240, 180),
        "habit_checkins": (15, 11), "expenses_total": (86.5, 120.0),
        "journal_entries": (4, 2), "reading_pages": (64, 40), "reading_sessions": (5, 3),
        "chat_turns": (38, 30),
    }
    metrics = [{"key": k, "current": sample[k][0], "previous": sample[k][1]} for k in METRIC_KEYS]
    w = Windows()
    text = ("This is a sample week — sign in and I'll show you your real one."
            if lang == "en" else "هاد أسبوع تجريبي — سجّل دخولك وبورجيك أسبوعك الحقيقي.")
    return {
        "demo": True, "week": w.iso_week(), "start": w.cur_start.isoformat(),
        "end": w.now.isoformat(), "metrics": metrics, "best_streak": 6,
        "sentence": text, "sentence_source": "template",
    }


__all__ = ["weekly_summary", "demo_summary", "template_sentence", "Windows",
           "collect", "CACHE_COLL", "METRIC_KEYS"]
