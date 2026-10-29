"""Every model call made outside a reply's own loop goes through `call`: the STM summary, a
chat's title, the daily nudge, photo tags, an expense's category, a time read from words,
an image's answer, a web summary, and a task's steps.

It is the one place such a call is made, so a limit or a cost cap is a line here when one is
needed (none is today). Each kind of work (``what``) may run on a deployment of its own
(`SANDY_BACKGROUND_MODELS`, a JSON object of what → Azure deployment); unset, it is the
chat's own (`AZURE_OPENAI_CHAT_DEPLOYMENT`, `sandy-chat`). Inside a turn the call is counted
in the turn's trace; outside one it is a background row for its user (`trace_store.background`).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.features import trace_store

logger = logging.getLogger(__name__)


def model_for(what: str) -> Optional[str]:
    """The deployment for this kind of work; None for the chat's own."""
    raw = os.getenv("SANDY_BACKGROUND_MODELS", "").strip()
    if not raw:
        return None
    try:
        models = json.loads(raw)
    except ValueError:
        logger.warning("[background] SANDY_BACKGROUND_MODELS is not JSON — the chat's model for all")
        return None
    chosen = models.get(what) if isinstance(models, dict) else None
    return str(chosen).strip() or None if chosen else None


def call(what: str, messages: List[Dict[str, Any]], *, user_id: Optional[str] = None,
         max_tokens: int = 500, temperature: float = 0.7,
         response_format: Optional[Dict[str, Any]] = None,
         tools: Optional[List[Dict[str, Any]]] = None) -> Any:
    """One model call for ``what``, its answer as chat completions gives it. Raises as the
    client does (`ConfigError` with no model, `OpenAIError`); the caller says what then."""
    from app.integrations.openai_client import chat_fn

    def ask():
        return chat_fn()(messages=messages, max_tokens=max_tokens, temperature=temperature,
                         response_format=response_format, tools=tools,
                         model_hint=model_for(what))

    if trace_store.current() is not None or not user_id:
        return ask()
    with trace_store.background(user_id, what):
        return ask()
