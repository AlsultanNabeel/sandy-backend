"""Voice session memory: identity/channel context vars and the STM history."""
from __future__ import annotations

import contextvars
from typing import Any, Dict, List, Optional

from app.api.voice_ws._config import logger
from app.brain import stm
from app.brain.context import RECENT_TURNS

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
    # Falls back to the voice thread itself for docs written before `user_id` was stored.
    return stm.recent_turns_for_user(chat_id, limit=RECENT_TURNS) or stm.load(chat_id, chat_id)


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


def _save_voice_turn(user_text: str, sandy_text: str,
                     user_id: str = "", channel: str = "") -> None:
    """Save a voice turn to STM, in the caller's tenant (the overflow summary is scoped).

    Identity and channel come in as arguments (this runs on a pool thread).
    """
    from app.api.voice_ws.tools import _voice_profile
    from app.utils.user_profiles import active_user_profile_context

    # Always set, even empty: pool threads keep context between jobs.
    set_voice_identity(user_id)
    set_voice_channel(channel)
    chat_id = _stm_chat_id()
    if not chat_id or not user_text or not sandy_text:
        return
    with active_user_profile_context(_voice_profile(chat_id)):
        stm.save(chat_id, chat_id, user_text, sandy_text, via=get_voice_channel(),
                 source="voice")


def load_recent_turns(user_id: str) -> List[Dict[str, Any]]:
    """_load_stm_history for a pool thread (identity as an argument)."""
    set_voice_identity(user_id)
    return _load_stm_history()
