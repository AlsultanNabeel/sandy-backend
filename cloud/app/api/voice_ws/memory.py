"""voice_ws memory."""
from __future__ import annotations
import logging

import time
from typing import Any, Dict, List, Optional
from app.api.voice_ws._config import (
    logger,
    _VOICE_CTX_TTL_S,
)

_voice_ctx_cache: dict[str, tuple[float, str]] = {}  # chat_id -> (built_at, text)


def _stm_chat_id() -> str:
    """The owner's canonical tenant id — same one users_store.get_or_create_owner()
    mints and /api/auth logs him in under, so voice shares one identity/memory
    space with REST/text-chat instead of keying off a raw legacy env var."""
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
    """Load STM as list of message dicts from MongoDB."""
    chat_id = _stm_chat_id()
    if not chat_id:
        return []
    try:
        from app.agent.graph.graph import _stm_load
        return _stm_load(chat_id, chat_id)
    except Exception as exc:
        logger.debug("[voice_ws] STM load skipped: %s", exc)
    return []


def _load_stm_context() -> str:
    """Load recent cross-platform conversation history from STM (text format)."""
    history = _load_stm_history()
    if not history:
        return ""
    turns = []
    for m in history[-10:]:
        role_label = "نبيل" if m.get("role") == "user" else "Sandy"
        content = m.get("content", "")
        if content:
            turns.append(f"{role_label}: {content}")
    if turns:
        return "\nآخر المحادثات عبر المنصات:\n" + "\n".join(turns)
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
        _stm_save(chat_id, chat_id, user_text, sandy_text)
    except Exception as exc:
        logger.debug("[voice_ws] STM save skipped: %s", exc)
    try:
        from app.db import get_db
        from app.agent.session_state import update_session_state
        update_session_state(chat_id, get_db(), platform="voice")
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
