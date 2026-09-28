"""Voice session memory: identity/channel context vars, STM history, and the memory seed."""
from __future__ import annotations

import contextvars
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from app.api.voice_ws._config import (
    logger,
    _VOICE_CTX_TTL_S,
)

# chat_id -> (built_at, text); bounded LRU (the TTL only makes stale entries unused).
_VOICE_CTX_MAX = 128
_voice_ctx_cache: "OrderedDict[str, tuple[float, str]]" = OrderedDict()

# Session identity, channel (robot vs app call) and speaker name live in context
# variables: per async task, safe across concurrent sessions. They don't reach
# pool threads, so pool functions take the identity as an explicit argument.
_identity: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sandy_voice_user", default="")
_channel_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sandy_voice_channel", default="")
# Resolved once per session so nothing on the audio path pays a Mongo read.
_speaker_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sandy_voice_speaker_name", default="")


def set_voice_channel(name: str) -> None:
    _channel_name.set(name or "")


def get_voice_channel() -> str:
    return _channel_name.get() or "الصوت"


def set_voice_identity(user_id: str) -> None:
    """مين بيحكي بهالجلسة — بالمصافحة، وبأول كل دالة بتشتغل ع خيط مجمّع."""
    _identity.set((user_id or "").strip())
    _speaker_name.set("")   # re-resolved lazily


def get_voice_identity() -> str:
    return _identity.get() or ""


def voice_speaker_label() -> str:
    """The session owner's display name, resolved once (runs on the audio loop; no per-sentence DB read)."""
    cached = _speaker_name.get()
    if cached:
        return cached
    name = resolve_speaker_label(get_voice_identity() or None)
    _speaker_name.set(name)
    return name


def resolve_speaker_label(user_id: str = "") -> str:
    """The blocking half — a Mongo read. Never call this on the audio loop."""
    from app.utils.user_profiles import speaker_label

    return speaker_label(user_id or get_voice_identity() or None)


def set_voice_speaker_label(name: str) -> None:
    """Store a name resolved on a pool thread into this context."""
    _speaker_name.set(name or "")


def _stm_chat_id() -> str:
    """Whose memory this session talks to: the connection's identity, set at the handshake."""
    ident = get_voice_identity()
    if ident:
        return ident

    # No fallback: unidentified means no memory, never someone else's.
    logger.warning("[voice_ws] unidentified session — starting with no memory")
    return ""


def _load_stm_history() -> List[Dict[str, Any]]:
    """Recent turns from every channel (voice, app chat), not just the voice thread."""
    chat_id = _stm_chat_id()
    if not chat_id:
        return []
    try:
        from app.agent.graph.graph import _stm_load, recent_turns_for_user
        shared = recent_turns_for_user(chat_id, limit=10)
        if shared:
            return shared
        # Legacy docs without user_id.
        return _stm_load(chat_id, chat_id)
    except Exception as exc:
        logger.debug("[voice_ws] STM load skipped: %s", exc)
    return []


def _load_stm_context(history: Optional[List[Dict[str, Any]]] = None) -> str:
    """آخر المحادثات من كل القنوات، وكل جملة موسومة بقناتها ووقتها."""
    # بيتمرّر من فوق لمّا يكون محمّل، عشان ما تنقرا مرّتين.
    history = _load_stm_history() if history is None else history
    if not history:
        return ""
    from app.utils.time_awareness import turn_stamp

    user_label = voice_speaker_label()
    turns = []
    for m in history[-10:]:
        role_label = user_label if m.get("role") == "user" else "Sandy"
        content = m.get("content", "")
        if not content:
            continue
        via = str(m.get("via") or "").strip()
        line = (f"[{via}] {role_label}: {content}" if via
                else f"{role_label}: {content}")
        ago = turn_stamp({"timestamp": m.get("timestamp")})
        turns.append(f"({ago}) {line}" if ago else line)
    if turns:
        return "\nآخر المحادثات عبر كل القنوات:\n" + "\n".join(turns)
    return ""


def session_context(history: Optional[List[Dict[str, Any]]] = None) -> str:
    """Fresh per-session context: the clock, time since the last message, and recent turns (never cached)."""
    from app.utils.time_awareness import time_awareness_block

    history = _load_stm_history() if history is None else history
    return ("\n" + time_awareness_block(history) + "\n(هاد وقت بداية المكالمة.)"
            + _load_stm_context(history))




def _voice_memory_context(message: str, *, include_semantic: bool) -> Optional[str]:
    """Voice-formatted memory context for the session owner, or None (caller falls back)."""
    chat_id = _stm_chat_id()
    if not chat_id:
        return None

    # Only the session-start seed is cacheable; per-turn semantic context is query-specific.
    cacheable = message == "" and not include_semantic
    if cacheable:
        cached = _voice_ctx_cache.get(chat_id)
        if cached and (time.monotonic() - cached[0]) < _VOICE_CTX_TTL_S:
            return cached[1]

    try:
        from app.agent.context_builder import build_memory_context, format_for_voice
        from app.db import get_db
        mongo_db = get_db()
        ctx = build_memory_context(
            chat_id=chat_id,
            user_id=chat_id,
            message=message,
            mongo_db=mongo_db,
            include_semantic=include_semantic,
            # Stable facts only: recent turns resurface as phantom replies on native audio.
            durable_only=True,
        )
        text = format_for_voice(ctx)
        if cacheable:
            _voice_ctx_cache[chat_id] = (time.monotonic(), text)
            _voice_ctx_cache.move_to_end(chat_id)
            while len(_voice_ctx_cache) > _VOICE_CTX_MAX:
                _voice_ctx_cache.popitem(last=False)
        return text
    except Exception as exc:
        logger.debug("[voice_ws] context_builder skipped: %s", exc)
        return None


def _save_voice_turn(user_text: str, sandy_text: str,
                     user_id: str = "", channel: str = "") -> None:
    """Save a voice turn to STM and run the same durable extraction as chat.

    Identity and channel come in as arguments (this runs on a pool thread).
    """
    # Always set, even empty: pool threads keep context between jobs.
    set_voice_identity(user_id)
    set_voice_channel(channel)
    chat_id = _stm_chat_id()
    if not chat_id or not user_text or not sandy_text:
        return
    try:
        from app.agent.graph.graph import _save_emotional_async, _stm_save
        _stm_save(chat_id, chat_id, user_text, sandy_text, via=get_voice_channel())
        # Same durable extraction as the chat turn (no mood on this path).
        from app.api.voice_ws.tools import _voice_profile
        from app.utils.user_profiles import active_user_profile_context
        with active_user_profile_context(_voice_profile(chat_id)):
            _save_emotional_async({}, user_text)
    except Exception as exc:
        logger.warning("[voice_ws] voice turn save failed: %s", exc)
    try:
        from app.db import get_db
        from app.agent.session_state import update_session_state
        update_session_state(chat_id, get_db(), platform="voice")
    except Exception:
        logger.debug("[voice_ws] session state update skipped", exc_info=True)


def load_recent_turns(user_id: str) -> List[Dict[str, Any]]:
    """_load_stm_history for a pool thread (identity as an argument)."""
    set_voice_identity(user_id)
    return _load_stm_history()
