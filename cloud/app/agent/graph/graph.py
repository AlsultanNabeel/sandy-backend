"""Sandy graph runner.

Pipeline:
  fc_router (single FC call) -> soul_node -> router_node
       -> route_after_router picks one of:
  pending_node | execute_node | clarify_node
       ->
  response_node -> SandyState with final_response ready

STM: loads conversation_history from MongoDB before the run, saves the user
message and reply after.
"""

from __future__ import annotations

import logging
import time
from datetime import timezone
from typing import Any, Dict, List, Optional

from app.utils.thread_pool import submit_background

from app.agent.graph.state import SandyState, create_initial_state, merge_state
from app.agent.nodes.soul import soul_node
from app.agent.nodes.router import router_node, route_after_router
from app.agent.nodes.pending import pending_node
from app.agent.nodes.execute import execute_node
from app.agent.nodes.clarify import clarify_node
from app.agent.nodes.response import response_node

logger = logging.getLogger(__name__)


# مزامنة STM


def load_stm(chat_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Public STM accessor for callers outside the graph (e.g. brainstorm)."""
    return _stm_load(chat_id, user_id)


# STM is backed by MongoDB, not Redis: Upstash's free tier hit its 500k/month
# request cap and STM saves started failing (memory froze). Mongo is already wired
# up, has no per-request quota, and costs nothing extra. One doc per chat:
#   { key: "<chat>:<user>", history: [...], updated_at: <datetime> }
# A TTL index on updated_at expires idle conversations after STM_TTL.
_STM_COLL = "sandy_stm"
_stm_index_ready = False


def _ensure_stm_indexes(coll) -> None:
    """Create the STM indexes, **each one independently**.

    They used to share a single `try`. One index failing therefore skipped every
    index after it, and the ready-flag was set anyway — so the skip was
    permanent for the life of the process and logged only at debug. The realistic
    trigger is not exotic: changing `STM_TTL` makes the `updated_at` index
    conflict with the one already in the database, and that would have silently
    cost the `(user_id, updated_at)` index below, which is the one holding up
    every chat turn.

    Same rule `bootstrap.py` already follows for the rest of the indexes, and
    for the same reason. Failures report at warning: a missing index does not
    break a feature, it just makes everything slower forever, which is exactly
    the kind of fault that needs to be visible to be found.
    """
    from app.utils.stm_config import STM_TTL

    jobs = (
        ("key", lambda: coll.create_index("key", unique=True, background=True)),
        ("updated_at_ttl", lambda: coll.create_index(
            "updated_at", expireAfterSeconds=STM_TTL, background=True)),
        # The index `recent_turns_for_user` needs, and did not have.
        #
        # That query filters on `user_id` and sorts by `updated_at`, and it runs
        # on **every** chat turn and twice at the start of every voice session.
        # With only the two above it was a collection scan of every conversation
        # on the server, so the cost of one person's reply grew with everybody
        # else's history. A compound index answers the filter and the sort
        # together, so Mongo never sorts in memory.
        ("user_id+updated_at", lambda: coll.create_index(
            [("user_id", 1), ("updated_at", -1)], background=True)),
    )
    for label, job in jobs:
        try:
            job()
        except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
            logger.warning("[graph] STM index %s failed: %s", label, exc)


def _stm_collection():
    """Return the MongoDB STM collection (and ensure its indexes once), or None
    if Mongo isn't wired up yet."""
    global _stm_index_ready
    try:
        from app.db import get_db
        mongo_db = get_db()
        if mongo_db is None:
            return None
        coll = mongo_db[_STM_COLL]
        if not _stm_index_ready:
            _ensure_stm_indexes(coll)
            _stm_index_ready = True
        return coll
    except Exception:
        return None


def _stm_load(chat_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Read STM from MongoDB (synchronous)."""
    coll = _stm_collection()
    if coll is None:
        return []
    try:
        doc = coll.find_one({"key": f"{chat_id}:{user_id}"}, {"_id": 0, "history": 1})
        return (doc or {}).get("history", []) or []
    except Exception as exc:
        logger.warning(f"[graph] STM load failed: {exc}")
        return []


def _is_duplicate_memory(
    mongo_db, chat_id: str, embedding: Optional[List[float]], threshold: float = 0.92
) -> bool:
    """Return True if a near-identical summary already exists (cosine similarity ≥ threshold)."""
    if not embedding or mongo_db is None:
        return False
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "sandy_vector_index",
                    "path": "embedding",
                    "queryVector": embedding,
                    "numCandidates": 10,
                    "limit": 1,
                    "filter": {
                        "chat_id": {"$eq": chat_id},
                        "label": "conversation_summary",
                    },
                }
            },
            {"$project": {"score": {"$meta": "vectorSearchScore"}}},
        ]
        results = list(mongo_db["sandy_memories"].aggregate(pipeline))
        return bool(results and results[0].get("score", 0) >= threshold)
    except Exception:
        return False


# Cached AzureOpenAI client for STM→LTM summarization. Built once (C4) instead of
# per STM overflow; rebuilt only if the underlying credentials change.
_summary_client = None
_summary_client_key: Optional[tuple] = None


def _get_summary_client():
    """Return the cached summarization client, building it once on first use."""
    global _summary_client, _summary_client_key
    from app.config import (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,
                            AZURE_OPENAI_API_VERSION)
    key = (AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_ENDPOINT)
    if _summary_client is None or _summary_client_key != key:
        from openai import AzureOpenAI
        _summary_client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
            max_retries=0,  # fail fast — the SDK's default retries silently triple any timeout
        )
        _summary_client_key = key
    return _summary_client


def _summarize_to_ltm(chat_id: str, user_id: str, messages: List[Dict[str, Any]]) -> None:
    """Summarize overflowing STM messages and save to MongoDB LTM (dedup-protected)."""
    try:
        from datetime import datetime, timezone
        from app.config import AZURE_OPENAI_API_KEY, AZURE_OPENAI_CHAT_DEPLOYMENT
        from app.db import get_db

        mongo_db = get_db()
        if mongo_db is None:
            logger.warning("[graph] STM→LTM skipped: mongo_db is None (facade not initialized?)")
            return
        if not AZURE_OPENAI_API_KEY:
            return

        from app.utils.user_profiles import resolve_display_name
        user_label = resolve_display_name(user_id, default="المستخدم")
        turns = "\n".join(
            f"{user_label if m['role'] == 'user' else 'Sandy'}: {m['content']}"
            for m in messages if m.get("content")
        )
        client = _get_summary_client()
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "لخّص المحادثة التالية في جملتين أو ثلاث بالعربي. ركّز على القرارات والمعلومات المهمة فقط."},
                {"role": "user", "content": turns},
            ],
            max_tokens=200,
        )
        summary = resp.choices[0].message.content.strip()
        if not summary:
            return

        # Compute embedding first for deduplication check
        vec: Optional[List[float]] = None
        try:
            from app.agent.semantic_memory import _embed
            vec = _embed(summary)
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

        if _is_duplicate_memory(mongo_db, chat_id, vec):
            logger.info(f"[graph] STM→LTM duplicate skipped for {chat_id}")
            return

        doc: Dict[str, Any] = {
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "label": "conversation_summary",
            "summary": summary,
            "source_turns": len(messages),
            "created_at": datetime.now(timezone.utc),
        }
        if vec:
            doc["embedding"] = vec
        mongo_db["sandy_memories"].insert_one(doc)
        logger.info(f"[graph] STM→LTM summary saved for {chat_id}")
    except Exception as exc:
        logger.debug(f"[graph] STM summarization failed: {exc}")


def _summarize_to_ltm_async(chat_id: str, user_id: str, messages: List[Dict[str, Any]]) -> None:
    submit_background(_summarize_to_ltm, chat_id, user_id, messages, _label="stm_summarize")


def _stm_save(
    chat_id: str,
    user_id: str,
    user_msg: str,
    assistant_reply: str,
    *,
    prior_history: Optional[List[Dict[str, Any]]] = None,
    via: str = "",
) -> None:
    """يحفظ رسالة المستخدم + رد ساندي في MongoDB. عملية قراءة + كتابة واحدة لكل
    دور؛ الفائض عن MAX_STM_MESSAGES بينلخّص للذاكرة بعيدة المدى.

    لو ``prior_history`` معطى (نفس الدور حمّله من بداية الـ run) منستخدمه ومنوفّر
    قراءة ثانية من MongoDB؛ غير هيك منقرأ بـ ``find_one`` كالمعتاد."""
    coll = _stm_collection()
    if coll is None:
        return
    try:
        from app.utils.stm_config import MAX_STM_MESSAGES
        from datetime import datetime

        key = f"{chat_id}:{user_id}"
        now = datetime.now(timezone.utc)
        ts = now.isoformat()

        if prior_history is not None:
            history: List[Dict[str, Any]] = list(prior_history)
        else:
            doc = coll.find_one({"key": key}, {"_id": 0, "history": 1})
            history = (doc or {}).get("history", []) or []

        # `via` = من وين انحكى الكلام.
        #
        # بدونه، الذاكرة الموحّدة بتصير كومة جُمَل بلا مكان. والمالك بيحكي مع
        # ساندي بتلات طرق، ومنطقي يسأل «إيمتى قلتلك هيك؟» — وهي لازم تعرف إذا
        # كان بالحكي مع الروبوت ولا مكتوب بالتطبيق، زي ما أي حدا بيتذكّر إذا
        # الحكي صار وجهًا لوجه ولا ع الهاتف.
        history.append({"role": "user", "content": user_msg, "timestamp": ts, "via": via})
        if assistant_reply:
            history.append({"role": "assistant", "content": assistant_reply,
                            "timestamp": ts, "via": via})
        if len(history) > MAX_STM_MESSAGES:
            _summarize_to_ltm_async(chat_id, user_id, history[:-MAX_STM_MESSAGES])
        history = history[-MAX_STM_MESSAGES:]

        coll.update_one(
            {"key": key},
            # `user_id` is stored as its own field, not left buried inside the
            # key string. It is what makes recent_turns_for_user() possible: one
            # person's last few turns can be read across every thread they have,
            # which is the difference between three memories and one.
            {"$set": {"history": history, "updated_at": now, "user_id": str(user_id)}},
            upsert=True,
        )
    except Exception as exc:
        logger.warning(f"[graph] STM save failed: {exc}")


def recent_turns_for_user(user_id: str, limit: int = 6) -> List[Dict[str, Any]]:
    """The last few turns this person had, **on any channel**.

    Short-term memory is stored per thread, and that is right: a chat should not
    have another chat's replies bleeding into it mid-sentence.

    But a person is not a thread. Sandy is reachable three ways — the robot in
    the room, the voice call in the app, and the app's text chat — and each one
    was writing to a different thread, so each one only remembered itself. Ask
    her something out loud, open the app thirty seconds later, and "what did we
    just say?" had no answer. The owner experienced that as amnesia; it was
    bookkeeping.

    Durable memory never had this problem: it is keyed by person. This gives the
    recent turns the same property, without merging the threads themselves —
    each channel keeps its own transcript, and every channel can see the last
    thing that happened anywhere.
    """
    coll = _stm_collection()
    if coll is None or not user_id:
        return []
    try:
        docs = coll.find(
            {"user_id": str(user_id)},
            {"_id": 0, "history": 1, "updated_at": 1},
        ).sort("updated_at", -1).limit(5)
        turns: List[Dict[str, Any]] = []
        for d in docs:
            turns.extend(d.get("history") or [])
        # Ordered by their own timestamps, not by which thread they came from:
        # interleaving is the point. A question asked aloud and answered in the
        # app is one conversation, and it should read like one.
        turns.sort(key=lambda m: str(m.get("timestamp") or ""))
        return turns[-limit:]
    except Exception as exc:  # noqa: BLE001 — memory is never worth a failed reply
        logger.warning(f"[graph] cross-channel STM read failed: {exc}")
        return []


# A1: حفظ اللحظة العاطفية في LTM (fire-and-forget)

_SIGNIFICANT_MOODS = {"stressed", "frustrated", "sad", "angry", "happy", "excited"}


def _save_emotional_async(state: "SandyState", message: str) -> None:
    """A1: يحفظ لحظة عاطفية + A3: يحفظ تصحيح أسلوبي — على الـ pool المشترك."""
    mood = state.get("mood") or ""
    chat_id = state.get("chat_id", "")
    user_id = state.get("user_id", "")

    def _do_save():
        # submit_background logs any exception (C1); no inner broad swallow here.
        from app.db import get_db

        mongo_db = get_db()
        if mongo_db is None:
            logger.warning("[graph] LTM save skipped: mongo_db is None (facade not initialized?)")
            return

        # A1: ذاكرة عاطفية
        if mood in _SIGNIFICANT_MOODS:
            from app.agent.emotional_ltm import save_emotional_moment
            save_emotional_moment(mood, message[:200])

        # A3: تصحيح أسلوبي
        from app.agent.style_memory import detect_style_correction, save_style_preference
        if detect_style_correction(message):
            save_style_preference(chat_id, user_id, message[:300], message, mongo_db)

        # #1: تسجيل وقت النشاط للصحة
        from app.agent.health_monitor import record_activity
        record_activity()

        # B2: استخراج وحفظ العلاقات (أخوي محمد، صديقتي سارة، ...)
        from app.agent.relationships_memory import save_detected_relationships
        save_detected_relationships(message)

        # D2: استخراج وحفظ الدروس المستفادة
        from app.agent.lessons_memory import save_detected_lesson
        save_detected_lesson(message)

        # F7: استخراج وحفظ المعالم المهمة (تخرج، زواج، انتقال، ...)
        from app.agent.shared_history import save_detected_milestone
        save_detected_milestone(message)

        # C2: تتبّع الاهتمامات (للمشاركة الذكية لاحقاً)
        from app.agent.interests_tracker import track_message_interests
        track_message_interests(message)

    submit_background(_do_save, _label="ltm_emotional")


# التوجيه


def _route_intent(state: "SandyState") -> "SandyState":
    """توجيه بنداء FC واحد على كامل كتالوج الأدوات.

    استبدلنا التصميم القديم (RouterAgent classify + specialist filtering = نداءين
    LLM متسلسلين) بنداء ``route_with_fc`` واحد يرى كل الأدوات ويختار مباشرة:
      • أسرع — نداء واحد بدل اثنين (~0.8–1.5s أقل لكل رسالة غير-chat).
      • أدق — ما في خطر "سوء تصنيف" يحجب الأداة الصح عن الموديل.
      • مش أغلى — prompt caching بيغطّي كتالوج الأدوات الثابت؛ والـ chat نفسه
        بيختاره الـ FC كـ chat_respond بدل نداء تصنيف منفصل.

    (الـ RouterAgent القديم + الـ specialists انحذفوا — ما عاد إلهم دور.)
    """
    from app.agent.agents.fc_router import route_with_fc
    from app.agent.tools.registry import get_registry

    declarations = get_registry().get_function_declarations()
    logger.info("[router] single-call FC routing with %d tools", len(declarations))
    return route_with_fc(state, declarations, agent_name="router")


# الـ graph runner


def run_graph(
    message: str,
    user_id: str,
    chat_id: str,
    *,
    pending_state: Optional[Dict[str, Any]] = None,
    source: str = "user",
    image_state: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
) -> SandyState:
    """ينفذ الـ Sandy pipeline كاملاً وتُرجع الـ SandyState النهائية.

    Args:
        message: رسالة المستخدم
        user_id: معرف المستخدم
        chat_id: معرف المحادثة
        pending_state: pending action نشط (اختياري)
        source: مصدر الرسالة (user / proactive / hardware)

    Returns:
        SandyState مع final_response جاهز للإرسال
    """
    # خيط ذاكرة المحادثة: conversation_id لو موجود (سيشن شات مستقلة) وإلا chat_id
    # (السلوك القديم تمامًا — تيليجرام/هاردوير/استدعاء بلا سيشن).
    thread_id = str(conversation_id or chat_id)

    # 1. حمّل conversation history من MongoDB (لهذا الخيط تحديدًا)
    history = _stm_load(thread_id, user_id)

    # ثم أضف اللي انقال ع القنوات التانية.
    #
    # هالخيط بيشوف حاله بس. والمالك بيحكي مع نفس ساندي بتلات طرق — الروبوت،
    # ومكالمة التطبيق، وشات التطبيق — فسؤال بالصوت وبعده سؤال مكتوب عن نفس
    # الموضوع كان بيوصل لواحدة ما سمعت الأول. وهي بتبيّن ناسية، وهي مش ناسية:
    # كانت بتقرا من دفتر تاني.
    #
    # الخيط بيضل صاحب الأولوية — سياقه المباشر أهم — والقنوات التانية بتنضاف
    # قبله كخلفية. وبنستثني اللي موجود أصلًا عشان ما ينعاد السطر مرّتين.
    # بلا `try` هون بالقصد: `recent_turns_for_user` بتمسك أخطاءها بنفسها وبترجّع
    # قائمة فاضية. حارس تاني فوقها بيخبّي غلط بالسطور اللي تحت — وهي اللي بتبني
    # السياق، يعني بالضبط المكان اللي غلطة فيه لازم تبيّن.
    cross = recent_turns_for_user(user_id, limit=6)
    if cross:
        seen = {(m.get("role"), m.get("content")) for m in history}
        extra = [m for m in cross if (m.get("role"), m.get("content")) not in seen]
        if extra:
            history = extra + history

    # 2. ابنِ الـ initial state
    state = create_initial_state(
        message=message,
        user_id=user_id,
        chat_id=chat_id,
        source=source,
        pending_state=pending_state,
        image_state=image_state,
        conversation_id=str(conversation_id or ""),
    )
    if history:
        state = merge_state(state, {"conversation_history": history})

    # 3. شغّل الـ pipeline — per-node latencies moved to Langfuse spans (R5).
    # Heroku logs نظيفة هلق؛ تفاصيل التوقيت موجودة في Langfuse traces.
    # نلفّ كل الـ pipeline بـ parent span واحد عشان كل شي (maestro LLM + tool
    # dispatch + ...) ينزل تحت trace واحد لكل رسالة تيليغرام بدل traces مبعثرة.
    rid = state["session_id"]
    t_total = time.perf_counter()

    try:
        # Start soul MongoDB queries in parallel with routing (~1.5s savings)
        try:
            from app.agent.nodes.soul import start_soul_prefetch
            _prefetch = start_soul_prefetch(
                state["chat_id"], state["user_id"], message,
                conversation_id=state.get("conversation_id") or "",
            )
            state = merge_state(state, {"soul_prefetch": _prefetch})
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

        # توجيه: نداء FC واحد على كامل الكتالوج
        state = _route_intent(state)

        state = soul_node(state)
        state = router_node(state)
        next_node = route_after_router(state)

        if next_node == "pending_node":
            state = pending_node(state)
        elif next_node == "clarify_node":
            state = clarify_node(state)
        else:
            state = execute_node(state)

        state = response_node(state)

    except Exception as exc:
        logger.error(
            f"[{rid}] pipeline failed ({(time.perf_counter()-t_total)*1000:.0f}ms): {exc}"
        )
        state = merge_state(
            state,
            {
                "final_response": "حصل خطأ، حاول مرة ثانية.",
                "error": str(exc),
            },
        )

    # 4. A1: احفظ لحظة عاطفية مهمة في LTM (background — لا يبطئ الرد)
    _save_emotional_async(state, message)

    # 5. احفظ في STM (MongoDB) — على نفس خيط المحادثة، فالفائض يتلخّص لذاكرة
    # بعيدة المدى مفهرسة بـ conversation_id (استرجاع دلالي لكل محادثة على حدة).
    final_reply = state.get("final_response") or ""
    # Reuse the history loaded in step 1 (same user, same turn) to skip a
    # redundant MongoDB read inside the save.
    _stm_save(thread_id, user_id, message, final_reply, prior_history=history,
              via="شات التطبيق" if source == "web" else (source or ""))

    # 6. حدّث الحالة المشتركة عبر المنصات (background)
    _update_session_state_async(state)

    return state


def _update_session_state_async(state: "SandyState") -> None:
    """Update cross-session state in background after every SA turn."""
    chat_id = state.get("chat_id", "")
    mood = state.get("mood") or ""
    if not chat_id:
        return

    def _do():
        # submit_background logs any exception (C1); no inner broad swallow here.
        from app.db import get_db
        from app.agent.session_state import update_session_state
        update_session_state(chat_id, get_db(), mood=mood, platform="app")

    submit_background(_do, _label="session_state")


def get_final_reply(state: SandyState) -> Dict[str, Any]:
    """يستخرج الرد النهائي جاهز للإرسال.

    **بلا تقطيع.** كان بيقسّم الردّ عند ٤٠٩٦ حرف — حدّ رسالة تيليجرام — ونقل
    تيليجرام انشال من المشروع. المستهلك الوحيد الباقي (`api/server.py`) كان
    بيلصق القطع فوراً بـ`"\n".join`، فالعملية صافي خسارة: بتقص عند مسافة أو
    سطر وبتحطّ مكانه سطر جديد، يعني بتقدر تكسر جملة بنصّها بردّ طويل.

    Returns:
        {"text": str, "reply_markup": Optional[dict], "image_bytes": Optional[bytes], "caption": str}
    """
    execution = state.get("execution_result") or {}
    return {
        "text": state.get("final_response") or "",
        "reply_markup": execution.get("reply_markup"),
        "image_bytes": execution.get("image_bytes"),
        "image_source": execution.get("image_source"),
        "caption": execution.get("caption", ""),
    }
