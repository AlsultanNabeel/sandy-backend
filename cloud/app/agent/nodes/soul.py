"""soul_node: يحقن الـ persona snippet في الـ state."""

from __future__ import annotations

import contextvars
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

from app.agent.graph.state import SandyState, merge_state
from app.agent.soul_vault import (
    get_persona, get_varied_snippet, get_gratitude_snippet,
    _DEFAULT_MINIMAL_PERSONA,
)
from app.agent.emotional_ltm import get_emotional_context
from app.agent.anomaly_detector import get_wellness_context
from app.agent.context_builder import get_persona_directives

logger = logging.getLogger(__name__)

# Shared executor reused across every turn — avoids per-request thread churn.
#
# **Sized so one turn's fan-out fits.** It is shared by every request in the
# worker and a turn submits up to eight jobs, so at four workers a single chat
# already queued its own work and the parallelism this pool exists to provide
# was gone. Eight is one turn, not eight turns: with `--threads 8` a busy worker
# can still queue, and a job that misses `_SOUL_WAIT_S` is dropped rather than
# waited for. That is the honest limit of this pool — sizing it for the worst
# case would mean sixty-four threads, which is a different trade and not one to
# make quietly.
_SOUL_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="soul")

# One deadline for everything on this pool.
#
# Two of the four collection sites called `fut.result()` with no timeout at all,
# so a hung Mongo query parked a gunicorn thread until the 120-second kill —
# while the other two gave up after three seconds on the same call. Same work,
# two policies; this is the one.
_SOUL_WAIT_S = 3.0


def _collect(name: str, fut):
    """Wait for one soul job, and **say so when it does not arrive.**

    Giving up is not free. `directives` is the whole persona — life snapshot,
    life search, onboarding line, preferences, relationships, lessons — and
    `soul_node` drops all of it on a `None`. Before this, the only trace was
    `directives=False` inside an INFO line, which is indistinguishable from a
    user who genuinely has no data. A user who is suddenly a stranger to her is
    worth a warning.
    """
    try:
        return fut.result(timeout=_SOUL_WAIT_S)
    except FuturesTimeoutError:
        logger.warning(
            "[soul] %s gave up after %.1fs — that block is missing from this turn",
            name, _SOUL_WAIT_S,
        )
    except Exception as exc:  # noqa: BLE001 — one job failing must not end the turn
        logger.warning("[soul] %s failed: %s", name, exc)
    return None


def _submit(fn, *args, **kwargs):
    """Submit to the soul pool **carrying the caller's context**.

    A pool worker starts with a blank set of context variables, and the active
    tenant profile is one — so a `scoped()` store called on a pool thread sees
    no tenant, reads nothing, writes nothing, and returns a perfectly ordinary
    empty result. Nothing raises. Nothing is logged. Sandy simply does not know
    the person she is talking to, and only on the paths that happen to be
    parallelised.

    That was live: the life snapshot and the life search are read through
    `scoped()` stores, and every caller of `get_persona_directives` here
    submitted it bare. Both blocks came back empty on every message, on chat and
    on voice — the same symptom as "she doesn't know my tasks", arriving from a
    threading detail rather than from the data.

    There was a helper for this (`_run_in_profile`) and it was applied to one
    call out of nine. **A rule that has to be remembered at each call site is
    not a rule**, so it lives in the submit instead: every job on this pool now
    carries the caller's context, and there is no bare `_SOUL_POOL.submit` left
    to forget.

    `copy_context()` rather than the profile alone, because the profile is not
    the only context variable in the system — the voice identity is another —
    and a copy takes whatever exists today and whatever is added later. A fresh
    copy per submit: a `Context` cannot be entered twice at once.
    """
    return _SOUL_POOL.submit(contextvars.copy_context().run, fn, *args, **kwargs)

_COMPLETION_TOOLS = frozenset({"task_complete", "goal_done", "task_delete"})
_CHAT_TOOLS = frozenset({"chat_respond", "chat_emotional", "chat_general"})
_GRATITUDE_SIGNALS = ("شكراً", "شكرا", "يسلمو", "يسلم", "مشكور", "ممنون", "تسلم", "thanks", "thank you")
_FAREWELL_SIGNALS = ("مع السلامة", "باي", "وداعاً", "وداعا", "تصبح على خير", "تصبحي", "bye", "good night", "لليلا", "لبكرا")
_FAREWELL_SNIPPETS = (
    "يلا، بحفظك الله 🤍 تواصل معي لما تحتاج",
    "مع السلامة، إنت دايماً بقلبي 🌙",
    "تصبح على خير — أنا هون لما ترجع",
    "باي باي! يومك كمان أحلى 🌟",
)
_PHILOSOPHICAL_SIGNALS = (
    "شو معنى", "ليش نحنا", "شو الهدف", "رأيك بـ", "رأيك في",
    "فلسفة", "الحياة والموت", "الوجود", "الوعي", "الحرية والمصير",
    "تؤمن", "تؤمني", "شو رأيك", "ما الفرق بين", "هل الإنسان",
    "هل يمكن", "الأخلاق", "الحقيقة المطلقة", "معنى الحياة",
)
# D3: مؤشرات التردد — Sandy تتعامل بصبر ولا تستعجل
_HESITATION_SIGNALS = (
    "مش متأكد", "مو متأكد", "ما متأكد", "يمكن", "ممكن نأجل",
    "بفكر", "بحتاج وقت", "حابب بس", "خايف", "متردد", "ما عارف",
    "ما بعرف", "لسا بفكر", "مش عارف", "محتار",
)
# D1: مؤشرات الفكاهة — المستخدم يحب المزح
_HUMOR_SIGNALS = (
    "هه", "ههه", "هاهاها", "هههه", "ضحكني", "ضحكتني",
    "😂", "🤣", "😆", "😹", "lol", "lmao", "haha",
)


def _get_mongo_db():
    try:
        from app.db import get_db
        return get_db()
    except Exception:
        return None


def _join(base: str | None, extra: str) -> str:
    return f"{base}\n{extra}" if base else extra


def _is_philosophical(message: str) -> bool:
    return any(sig in message for sig in _PHILOSOPHICAL_SIGNALS)


def _is_hesitating(message: str) -> bool:
    return any(sig in message for sig in _HESITATION_SIGNALS)


def _is_humorous(message: str) -> bool:
    msg_lower = message.lower()
    return any(sig in msg_lower for sig in _HUMOR_SIGNALS)


def _log_retrieval_eval_async(chat_id: str, query: str, summaries: list, facts: list) -> None:
    """Async save of retrieval event to sandy_evals for quality monitoring."""
    import threading

    def _save():
        try:
            from datetime import datetime, timezone
            from app.db import get_db
            mongo_db = get_db()
            if mongo_db is None:
                return
            mongo_db["sandy_evals"].insert_one({
                "chat_id": str(chat_id),
                "query": query[:200],
                "summaries_count": len(summaries),
                "facts_count": len(facts),
                "summary_sample": summaries[:1],
                "fact_sample": facts[:1],
                "created_at": datetime.now(timezone.utc),
            })
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

    threading.Thread(target=_save, daemon=True).start()


def soul_node(state: SandyState) -> SandyState:
    """LangGraph node: يحقن persona_snippet في الـ state."""
    _t_soul = time.perf_counter()
    try:
        message = state.get("message", "").strip()
        fc_name = (state.get("function_call") or {}).get("name", "")
        mood = state.get("mood") or "neutral"
        chat_id = state.get("chat_id", "")
        user_id = state.get("user_id", "")
        mongo_db = _get_mongo_db()

        # Stage 1: استعلامات Mongo بالتوازي
        prefetch = state.get("soul_prefetch")
        if prefetch:
            # Prefetch (comfort + directives only) started before maestro.
            _s1 = {}
            for k, fut in prefetch.items():
                if k.startswith("__"):
                    continue   # prefetched semantic search — collected in stage2
                _s1[k] = _collect(k, fut)
        else:
            # Fallback: run the always-needed queries now (no prefetch available)
            _get_proactive_comfort = None
            try:
                from app.agent.proactive_comfort import get_proactive_comfort as _get_proactive_comfort
            except Exception:
                logger.debug("ignoring non-critical error", exc_info=True)

            _s1_futs = {}
            if _get_proactive_comfort:
                _s1_futs["comfort"] = _submit(
                    _get_proactive_comfort, chat_id, user_id, mongo_db, message=message
                )
            _s1_futs["directives"] = _submit(
                get_persona_directives, chat_id, user_id, mongo_db, message=message)

            _s1 = {}
            for k, fut in _s1_futs.items():
                _s1[k] = _collect(k, fut)

        # Chat-only context (dreams/anniv/future) is fetched here — only for chat
        # tools — since routing has run and fc_name is now known. Avoids wasting
        # Mongo round-trips on task/calendar messages.
        if fc_name in _CHAT_TOOLS:
            _get_dreams_ctx = _get_anniv_ctx = _get_future_ctx = None
            try:
                from app.agent.dreams_engine import get_dreams_context as _get_dreams_ctx
            except Exception:
                logger.debug("ignoring non-critical error", exc_info=True)
            try:
                from app.agent.shared_history import get_anniversary_context as _get_anniv_ctx
            except Exception:
                logger.debug("ignoring non-critical error", exc_info=True)
            try:
                from app.agent.future_messages import get_future_messages_context as _get_future_ctx
            except Exception:
                logger.debug("ignoring non-critical error", exc_info=True)

            _chat_futs = {}
            if _get_dreams_ctx:
                _chat_futs["dreams"] = _submit(_get_dreams_ctx, chat_id, user_id, mongo_db)
            if _get_anniv_ctx:
                _chat_futs["anniv"] = _submit(_get_anniv_ctx, chat_id, user_id, mongo_db)
            if _get_future_ctx:
                _chat_futs["future"] = _submit(_get_future_ctx, chat_id, user_id, mongo_db)
            try:
                from app.agent.proactive_goals import get_goals_followup_context
                _chat_futs["goals"] = _submit(
                    get_goals_followup_context, chat_id, user_id, mongo_db
                )
            except Exception:
                logger.debug("ignoring non-critical error", exc_info=True)

            for k, fut in _chat_futs.items():
                _s1[k] = _collect(k, fut)

        logger.info(f"[soul] stage1: {(time.perf_counter()-_t_soul)*1000:.0f}ms")

        # المواساة + اختيار الـ persona
        comfort_override = None
        comfort_directive = None
        comfort = _s1.get("comfort")
        if comfort:
            comfort_override, comfort_directive = comfort

        if comfort_override:
            intensity_override = comfort_override
        elif fc_name in _COMPLETION_TOOLS:
            intensity_override = "playful"
        else:
            intensity_override = None

        result = get_persona(
            user_id=state["user_id"],
            intensity=intensity_override or state.get("persona_intensity"),
            mood=mood,
        )

        if fc_name in _CHAT_TOOLS and result["intensity"] in ("standard", "playful", "empathetic"):
            snippet = get_varied_snippet(result["intensity"], mood) or result["snippet"] or None
        else:
            snippet = result["snippet"] or None

        if any(sig in message for sig in _GRATITUDE_SIGNALS):
            snippet = get_gratitude_snippet()
        elif any(sig in message for sig in _FAREWELL_SIGNALS):
            snippet = random.choice(_FAREWELL_SNIPPETS)

        # B5: حقن توجيه المواساة الاستباقية إن وُجد (critical override فقط)
        if comfort_directive and comfort_override:
            snippet = _join(snippet, comfort_directive)

        # Stage 2: استعلامات شرطية بالتوازي
        intensity = result["intensity"]
        _s2_futs = {}
        if intensity in ("empathetic", "standard"):
            _s2_futs["emo"] = _submit(
                get_emotional_context, chat_id=chat_id, user_id=user_id, mongo_db=mongo_db
            )
        if intensity == "empathetic":
            _s2_futs["wellness"] = _submit(
                get_wellness_context, chat_id=chat_id, user_id=user_id, mongo_db=mongo_db
            )
        if message:
            pf = state.get("soul_prefetch") or {}
            if "__semantic" in pf:
                # Already started during prefetch (overlapped the router) — just collect.
                _s2_futs["__semantic"] = pf["__semantic"]
            else:
                try:
                    from app.agent.semantic_memory import search_memory_for_turn
                    # ملخّصات هذا الخيط (سيشن الشات) لو موجود، وإلا chat_id (السلوك القديم).
                    _summ_thread = state.get("conversation_id") or chat_id
                    _s2_futs["__semantic"] = _submit(
                        search_memory_for_turn, message, _summ_thread)
                except Exception:
                    logger.debug("ignoring non-critical error", exc_info=True)

        _s2 = {}
        for k, fut in _s2_futs.items():
            _s2[k] = _collect(k, fut)
        _sem = _s2.pop("__semantic", None) or {}
        _s2["summaries"] = _sem.get("summaries") or []
        _s2["sem_facts"] = _sem.get("facts") or []

        logger.info(f"[soul] stage2: {(time.perf_counter()-_t_soul)*1000:.0f}ms")

        # سجّل نتائج الاسترجاع للتقييم
        _n_summaries = len(_s2.get("summaries") or [])
        _n_facts = len(_s2.get("sem_facts") or [])
        logger.info(
            "[soul][eval] chat=%s summaries=%d facts=%d directives=%s",
            (chat_id or "")[:8], _n_summaries, _n_facts, bool(_s1.get("directives")),
        )
        if _n_summaries or _n_facts:
            _log_retrieval_eval_async(chat_id, message, _s2.get("summaries") or [], _s2.get("sem_facts") or [])

        # ركّب الـ snippet
        if _s2.get("emo"):
            snippet = _join(snippet, _s2["emo"])
        if _s2.get("summaries"):
            summaries_text = " | ".join(_s2["summaries"][:2])
            snippet = _join(snippet, f"[ملخصات ذات صلة: {summaries_text}]")
        if _s2.get("sem_facts"):
            facts_text = " | ".join(_s2["sem_facts"][:3])
            snippet = _join(snippet, f"[معلومات ذات صلة: {facts_text}]")
        if _s1.get("directives"):
            snippet = _join(snippet, _s1["directives"])

        # حالة المستخدم عبر الجلسات
        try:
            from app.agent.session_state import get_session_state
            ss = get_session_state(chat_id, mongo_db)
            if ss:
                ss_parts = []
                if ss.get("last_mood") and ss["last_mood"] not in ("neutral",):
                    ss_parts.append(f"مزاجه الأخير: {ss['last_mood']}")
                if ss.get("last_platform"):
                    ss_parts.append(f"آخر منصة استخدمها: {ss['last_platform']}")
                if ss.get("recent_topics"):
                    ss_parts.append("مواضيع أخيرة: " + "، ".join(ss["recent_topics"][-3:]))
                if ss_parts:
                    snippet = _join(snippet, "[حالة المستخدم: " + " | ".join(ss_parts) + "]")
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

        # وضع العصف الذهني نشط: سلوك شريكة التفكير طول الجلسة
        try:
            from app.features.brainstorm import get_active
            active_bs = get_active(chat_id)
            if active_bs:
                snippet = _join(
                    snippet,
                    f"[وضع عصف ذهني نشط عن «{active_bs.get('topic', '')}»: إنتِ شريكة "
                    "تفكير **ذكية وخبيرة** — مش مسجّلة نقاط ولا منفّذة أوامر.\n"
                    "• لما يسأل «شو رأيك / شو بتقترحي» اعطيه **اقتراحات ملموسة وخيارات "
                    "ورأيك الصريح** فورًا — لا ترجّعي السؤال عليه.\n"
                    "• **صحّحي المفاهيم الغلط بصراحة واشرحي ليش** — لا توافقي على طول ولا "
                    "تجاملي ولا تكتفي بردود سطحية. لو فكرته ناقصة قوليله وكمّليها.\n"
                    "• ناقشي بعمق وحرية، اطرحي أسئلة ذكية توسّع تفكيره، وشاركي خبرتك.\n"
                    "• ضلّي بالنقاش المفتوح لحد ما هو يقرّر — لا تستعجلي التلخيص.\n"
                    "• ردّك الأساسي = نقاش حقيقي. استعملي brainstorm_add **بصمت وفقط** "
                    "لتسجيل قرار/عنصر نهائي اتفقتوا عليه — مش كل رسالة، ومش بدل النقاش.\n"
                    "• «لخّصي/خلصنا» → brainstorm_finish · «ألغي/بطّلي» → brainstorm_cancel.]",
                )
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

        if _is_philosophical(message):
            snippet = _join(snippet, "[نبرة: تعمّقي في النقاش، شاركي رأيك الحقيقي، لا تكتفي بالإجابات السطحية]")
        if _is_hesitating(message):
            snippet = _join(snippet, "[نبرة: المستخدم متردد — لا تستعجلي، اقترحي تأجيل أو خطوة صغيرة، اسأليه عن مخاوفه]")
        if _is_humorous(message) and intensity in ("standard", "playful"):
            snippet = _join(
                snippet,
                "[نبرة: المستخدم ضحك — ابدأي ردك بضحكة لطيفة فعلية مثل "
                "'ههههه' أو 'هاهاها 😄' (TTS رح يلفظها بصوت)، ثم رد قصير يكمل الجو المرح. "
                "لا ترفضي المزح ولا تكوني جدية]",
            )

        if _s2.get("wellness"):
            snippet = _join(snippet, _s2["wellness"])
        if _s1.get("goals"):
            snippet = _join(snippet, _s1["goals"])
        if _s1.get("dreams"):
            snippet = _join(snippet, _s1["dreams"])
        if _s1.get("anniv"):
            snippet = _join(snippet, _s1["anniv"])
        if _s1.get("future"):
            snippet = _join(snippet, _s1["future"])

        # لو البحث الدلالي رجّع ذكريات ذات صلة والرسالة قصيرة/مفتوحة،
        # خلّيها تشير لها بعفوية بدون فرض.
        if (_s2.get("sem_facts") or _s2.get("summaries")) and 0 < len(message.split()) <= 7:
            snippet = _join(
                snippet,
                "[استباقي: إذا رأيتِ فرصة طبيعية في الحوار، أشيري بعفوية لإحدى الذكريات أو المعلومات أعلاه]",
            )

        logger.info(f"[soul] total: {(time.perf_counter()-_t_soul)*1000:.0f}ms")
        return merge_state(state, {
            "persona_intensity": result["intensity"],
            "persona_snippet": snippet,
        })

    except Exception as exc:
        logger.error(f"[soul_node] Soul Vault failed: {exc}")
        return merge_state(state, {
            "persona_intensity": "minimal",
            "persona_snippet": _DEFAULT_MINIMAL_PERSONA or None,
        })


def start_soul_prefetch(chat_id: str, user_id: str, message: str,
                        conversation_id: str = "") -> dict:
    """Eagerly starts the always-needed soul MongoDB queries before maestro runs.

    Only the queries needed for EVERY message (comfort + directives) are
    prefetched here, since routing has not run yet and chat-only context
    (dreams/anniv/future) would be wasted on task/calendar messages.
    soul_node fetches those conditionally once fc_name is known.

    Returns a dict of Future objects. Attach to state['soul_prefetch'] so
    soul_node can collect results without waiting a second time.
    """
    mongo_db = _get_mongo_db()
    futures: dict = {}

    try:
        from app.agent.proactive_comfort import get_proactive_comfort as _gpc
        futures["comfort"] = _submit(_gpc, chat_id, user_id, mongo_db, message=message)
    except Exception:
        logger.debug("ignoring non-critical error", exc_info=True)

    # `message=` matters: it is what opens the life-search block inside
    # `get_persona_directives`. Omitting it meant the chat path could see the
    # four-item life *snapshot* and never the detail behind it — ask about a
    # book that is not among the newest four and she had no idea it was hers.
    futures["directives"] = _submit(
        get_persona_directives, chat_id, user_id, mongo_db, message=message)

    # Semantic memory search only needs the message — start it here so it overlaps
    # the router FC call (~4s) instead of running serially after it in stage2.
    # The "__" keys are collected later in stage2, not awaited in stage1.
    if message:
        try:
            from app.agent.semantic_memory import search_memory_for_turn
            # ملخّصات خيط المحادثة (سيشن الشات) لو موجود، وإلا chat_id (السلوك القديم).
            _summ_thread = conversation_id or chat_id
            # وظيفة وحدة مش تنتين: الاتنين كانوا يعملوا تضمين لنفس النص، يعني
            # نداءين لـ OpenAI بكل رسالة عشان استعلام واحد.
            futures["__semantic"] = _submit(
                search_memory_for_turn, message, _summ_thread)
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

    return futures
