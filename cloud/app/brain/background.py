"""Every model call made outside a reply's own loop goes through `call`: the STM summary, a
chat's title, the daily nudge, photo tags, an expense's category, a time read from words,
an image's answer, a web summary, and a task's steps.

It is the one place such a call is made, so a limit or a cost cap is a line here when one is
needed (none is today). Each kind of work (``what``) may run on a deployment of its own
(`SANDY_BACKGROUND_MODELS`, a JSON object of what → Azure deployment); unset, it is the
chat's own (`AZURE_OPENAI_CHAT_DEPLOYMENT`, `sandy-chat`). Inside a turn the call is counted
in the turn's trace; outside one it is a background row for its user (`trace_store.background`).

Every call says how urgent it is (`priority`). There is no queue here: a call runs in the
thread that makes it, so DIRECT (what the user waits on: a time read, a web summary, an
image's answer) never waits behind BACKGROUND work (a summary, a title, tags, a category,
the daily nudge), which runs on the shared pool, nor behind SCHEDULED (a task's steps), the
only kind that may go as a batch (`may_batch`). A batch is submitted here too (`call` with
``as_batch``, while `batching` says batches are on) and its answer read here (`collect`), so a
limit at this one place covers it; `brain/batch.py` is only Azure's client for it.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.features import trace_store

logger = logging.getLogger(__name__)

DIRECT, BACKGROUND, SCHEDULED = "direct", "background", "scheduled"
PRIORITIES = (DIRECT, BACKGROUND, SCHEDULED)


def may_batch(priority: str) -> bool:
    """Only a scheduled task waits long enough for a batch; nothing the user waits on does."""
    return priority == SCHEDULED


def batching(priority: str) -> bool:
    """Whether a call of this priority may go as a batch now (`brain/batch.py`: off unless set up)."""
    from app.brain import batch
    return batch.enabled(priority)


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


def call(what: str, messages: List[Dict[str, Any]], *, priority: str,
         user_id: Optional[str] = None,
         max_tokens: int = 500, temperature: float = 0.7,
         response_format: Optional[Dict[str, Any]] = None,
         tools: Optional[List[Dict[str, Any]]] = None, as_batch: bool = False) -> Any:
    """One model call for ``what``, its answer as chat completions gives it. Raises as the
    client does (`ConfigError` with no model, `OpenAIError`); the caller says what then.
    With ``as_batch`` it is submitted as a batch job instead (ValueError unless `batching`
    allows its priority) and the job's id comes back; `collect` reads the answer."""
    from app.integrations.openai_client import chat_fn

    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {PRIORITIES}, got {priority!r}")
    if as_batch:
        if not batching(priority):
            raise ValueError(f"{what} may not go as a batch now")
        from app.brain import batch
        return batch.submit(what, messages, max_tokens=max_tokens, temperature=temperature)

    def ask():
        with trace_store.doing(what):
            return chat_fn()(messages=messages, max_tokens=max_tokens, temperature=temperature,
                             response_format=response_format, tools=tools,
                             model_hint=model_for(what))

    if trace_store.current() is not None or not user_id:
        return ask()
    with trace_store.background(user_id, what):
        return ask()


def collect(what: str, job_id: str, *, user_id: Optional[str] = None) -> Optional[str]:
    """A batch job's answer (`call` with ``as_batch``): its text once Azure has it, None while it
    runs; raises when the job failed or expired. Its tokens are counted as ``what``."""
    from app.brain import batch

    def read():
        with trace_store.doing(what):
            return batch.collect(job_id)

    if trace_store.current() is not None or not user_id:
        return read()
    with trace_store.background(user_id, what):
        return read()
