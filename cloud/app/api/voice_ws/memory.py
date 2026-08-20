"""voice_ws memory."""
from __future__ import annotations
import logging

import threading
import time
from typing import Any, Dict, List, Optional
from app.api.voice_ws._config import (
    logger,
    _VOICE_CTX_TTL_S,
)

_voice_ctx_cache: dict[str, tuple[float, str]] = {}  # chat_id -> (built_at, text)

# أي جسم بيحكي — الروبوت اللي بالغرفة ولا مكالمة التطبيق.
#
# التنين بيدخلوا من نفس المقبس وبيشاركوا نفس الذاكرة، وهاد صح. بس المالك بيسأل
# «إيمتى قلتلك؟»، والفرق بين «حكيتيلي وإنتي واقفة قدّامي» و«حكيتيلي بالمكالمة»
# فرق حقيقي عنده — زي ما أي حدا بيتذكّر إذا الكلام صار وجهًا لوجه ولا ع الهاتف.
#
# `threading.local` لأنّ كل اتصال بخيطه الخاص عند flask-sock، فما في خلط بين
# جلستين شغّالين بنفس اللحظة.
_channel = threading.local()


def set_voice_channel(name: str) -> None:
    _channel.name = name


def get_voice_channel() -> str:
    return getattr(_channel, "name", "") or "الصوت"


def set_voice_identity(user_id: str) -> None:
    """مين بيحكي بهالجلسة — بينحدّد مرّة عند المصافحة.

    قبل هيك كانت الذاكرة الصوتية بتنادي «المالك» من متغيّر بيئة: حساب واحد
    ثابت لكل جلسة صوت بالنظام. اشتغل لأنه كان في شخص واحد. وأول ما صار في
    تسجيل دخول بأبل وجوجل، صار معناها إنّ **كل زبون بيحكي مع ذاكرة زبون تاني**
    — وهاد مش خلل واجهة، هاد تسريب.
    """
    _channel.user = (user_id or "").strip()


def get_voice_identity() -> str:
    return getattr(_channel, "user", "") or ""


def _stm_chat_id() -> str:
    """Whose memory this session is talking to.

    **The identity of the connection, not a global one.** It is set once at the
    handshake — from the app's token, or from the robot's pairing record — and
    everything this session reads or writes is scoped to it.

    It used to resolve `users_store.get_or_create_owner()`: a single account,
    from an environment variable, for every voice session on the server. That
    was invisible while there was one user and catastrophic the moment there
    were two — a second customer would have been handed the first one's diary.

    The fallback below is for a robot nobody has paired yet. It keeps the old
    single-owner behaviour for an existing install, and returns empty for a
    fresh one, which makes her memoryless rather than someone else's.
    """
    ident = get_voice_identity()
    if ident:
        return ident
    try:
        from app.features import users_store
        uid = users_store.get_or_create_owner()
        if uid:
            return uid
    except Exception as exc:
        logger.debug("[voice_ws] owner tenant lookup failed: %s", exc)
    from app.utils.user_profiles import OWNER_CHAT_ID, LEGACY_OWNER_CHAT_ID
    return OWNER_CHAT_ID or LEGACY_OWNER_CHAT_ID or ""


def _load_stm_history() -> List[Dict[str, Any]]:
    """Recent turns from **every** channel, not just the voice thread.

    The voice thread and the app's chat threads are separate documents, so
    reading only this one meant the robot could not remember a conversation the
    owner had in the app a minute earlier — and the app could not remember what
    he had just said out loud. Three doors into the same house, three memories.

    The voice thread's own turns are still in here; they are simply no longer
    the only ones.
    """
    chat_id = _stm_chat_id()
    if not chat_id:
        return []
    try:
        from app.agent.graph.graph import _stm_load, recent_turns_for_user
        shared = recent_turns_for_user(chat_id, limit=10)
        if shared:
            return shared
        # Older documents predate the user_id field and cannot be found by it.
        # Falling back keeps memory working through the deploy rather than
        # starting the owner from nothing.
        return _stm_load(chat_id, chat_id)
    except Exception as exc:
        logger.debug("[voice_ws] STM load skipped: %s", exc)
    return []


def _load_stm_context() -> str:
    """آخر المحادثات من كل القنوات، وكل جملة مكتوب جنبها من وين إجت.

    المصدر مش زينة. المالك بيحكي مع نفس ساندي بتلات طرق، ومنطقي يسأل «إيمتى
    قلتلك هيك؟» — والجواب «بالمكالمة» غير «وإنت واقف قدّامي». بلا الوسم، الذاكرة
    الموحّدة بتصير كومة جُمَل بلا مكان، وهي ما بتقدر تجاوب عن سؤال هي حاضرة فيه.
    """
    history = _load_stm_history()
    if not history:
        return ""
    turns = []
    for m in history[-10:]:
        role_label = "نبيل" if m.get("role") == "user" else "Sandy"
        content = m.get("content", "")
        if not content:
            continue
        via = str(m.get("via") or "").strip()
        turns.append(f"[{via}] {role_label}: {content}" if via
                     else f"{role_label}: {content}")
    if turns:
        return "\nآخر المحادثات عبر كل القنوات:\n" + "\n".join(turns)
    return ""


# Tiny in-process cache for the durable session-start seed. The seed is built
# with durable_only=True (stable facts only), so reusing it for a few seconds
# makes reconnects/rapid re-opens effectively instant without staleness risk.


def _voice_memory_context(message: str, *, include_semantic: bool) -> Optional[str]:
    """Shared rich-context builder for the voice helpers.

    Returns the voice-formatted memory context for the owner chat, or ``None``
    if there's no owner or the context builder is unavailable (caller decides
    the fallback). Centralizes the context_builder/mongo_db imports that used to
    be repeated across the voice helpers.
    """
    chat_id = _stm_chat_id()
    if not chat_id:
        return None

    # Only the session-start seed (empty message, no semantic) is cacheable —
    # per-turn semantic context is query-specific and must never be reused.
    cacheable = message == "" and not include_semantic
    if cacheable:
        cached = _voice_ctx_cache.get(chat_id)
        if cached and (time.monotonic() - cached[0]) < _VOICE_CTX_TTL_S:
            return cached[1]

    try:
        from app.agent.context_builder import build_memory_context, format_for_voice
        from app.db import get_db
        mongo_db = get_db()
        stm_history = _load_stm_history()
        ctx = build_memory_context(
            chat_id=chat_id,
            user_id=chat_id,
            message=message,
            mongo_db=mongo_db,
            stm_history=stm_history,
            include_semantic=include_semantic,
            # Voice seed = stable facts only. Recent topics/summaries/STM turns
            # are the exact text that resurfaces as phantom replies on the
            # native-audio model, which can't be told to ignore them.
            durable_only=True,
        )
        text = format_for_voice(ctx)
        if cacheable:
            _voice_ctx_cache[chat_id] = (time.monotonic(), text)
        return text
    except Exception as exc:
        logger.debug("[voice_ws] context_builder skipped: %s", exc)
        return None


def _save_voice_turn(user_text: str, sandy_text: str) -> None:
    """Save voice turn to STM (MongoDB) + update cross-session state."""
    chat_id = _stm_chat_id()
    if not chat_id or not user_text or not sandy_text:
        return
    try:
        from app.agent.graph.graph import _stm_save
        _stm_save(chat_id, chat_id, user_text, sandy_text, via=get_voice_channel())
    except Exception as exc:
        logger.debug("[voice_ws] STM save skipped: %s", exc)
    try:
        from app.db import get_db
        from app.agent.session_state import update_session_state
        update_session_state(chat_id, get_db(), platform="voice")
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
