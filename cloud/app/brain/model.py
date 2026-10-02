"""The one model call: messages + tools in, text or tool calls out.

The Azure chat deployment through `openai_client.chat_fn` (breaker + param
quirks), then OpenAI direct with ``OPENAI_MODEL``, then give up.

`/api/agent/stream` sets the stream hooks on the thread that runs the turn; the
loop streams the reply's text through them, cumulative.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.config import OPENAI_MODEL
from app.integrations.openai_client import DEFAULT_CHAT_TIMEOUT_S, chat_fn, openai_direct_client

logger = logging.getLogger(__name__)

MAX_TOKENS = 700
TEMPERATURE = 0.5

_stream_tls = threading.local()


def set_stream_hooks(on_start: Callable[[], None], on_chunk: Callable[[str], None],
                     on_step: Optional[Callable[[str], None]] = None) -> None:
    _stream_tls.on_start = on_start
    _stream_tls.on_chunk = on_chunk
    _stream_tls.on_step = on_step


def clear_stream_hooks() -> None:
    _stream_tls.on_start = None
    _stream_tls.on_chunk = None
    _stream_tls.on_step = None


def step_hook() -> Optional[Callable[[str], None]]:
    """Told each tool's name before it runs, so the screen can say what is happening."""
    return getattr(_stream_tls, "on_step", None)


def stream_hooks():
    """(on_start, on_chunk) when this thread is streaming, else None."""
    on_start = getattr(_stream_tls, "on_start", None)
    on_chunk = getattr(_stream_tls, "on_chunk", None)
    return (on_start, on_chunk) if on_start and on_chunk else None


@dataclass
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any]


@dataclass
class Reply:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)


def _parse_args(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _from_message(msg: Any) -> Reply:
    calls = []
    for i, tc in enumerate(getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", "") if fn else ""
        if name:
            calls.append(ToolCall(getattr(tc, "id", None) or f"call_{i}", name,
                                  _parse_args(getattr(fn, "arguments", None))))
    return Reply(text=(getattr(msg, "content", None) or "").strip(), tool_calls=calls)


def _from_stream(stream: Any, on_text: Callable[[str], None]) -> Reply:
    """Accumulate a streamed answer; text deltas go out as they arrive (cumulative)."""
    text = ""
    parts: Dict[int, Dict[str, str]] = {}
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None) or ""
        if piece:
            text += piece
            on_text(text)
        for tc in getattr(delta, "tool_calls", None) or []:
            slot = parts.setdefault(getattr(tc, "index", 0) or 0,
                                    {"id": "", "name": "", "args": ""})
            slot["id"] = getattr(tc, "id", None) or slot["id"]
            fn = getattr(tc, "function", None)
            if fn is not None:
                slot["name"] += getattr(fn, "name", None) or ""
                slot["args"] += getattr(fn, "arguments", None) or ""
    calls = [ToolCall(p["id"] or f"call_{i}", p["name"], _parse_args(p["args"]))
             for i, p in sorted(parts.items()) if p["name"]]
    return Reply(text=text.strip(), tool_calls=calls)


def _primary(messages, tools, stream: bool):
    return chat_fn()(messages=messages, tools=tools, stream=stream,
                     max_tokens=MAX_TOKENS, temperature=TEMPERATURE)


def _openai_direct(messages, tools):
    client = openai_direct_client()
    if client is None:
        return None
    # The API refuses an empty tools list; a summary call sends none.
    extra = {"tools": tools} if tools else {}
    return client.chat.completions.create(
        model=OPENAI_MODEL, messages=messages, **extra,
        max_tokens=MAX_TOKENS, temperature=TEMPERATURE, timeout=DEFAULT_CHAT_TIMEOUT_S)


def complete(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]],
             on_text: Optional[Callable[[str], None]] = None) -> Optional[Reply]:
    """One model step, or None when every provider failed."""
    try:
        if on_text is not None:
            return _from_stream(_primary(messages, tools, stream=True), on_text)
        resp = _primary(messages, tools, stream=False)
        return _from_message(resp.choices[0].message)
    except Exception as exc:  # noqa: BLE001 — provider boundary; fall back below
        logger.warning("[brain] primary model failed, trying OpenAI direct: %s", exc)
    try:
        resp = _openai_direct(messages, tools)
        if resp is None:
            return None
        return _from_message(resp.choices[0].message)
    except Exception as exc:  # noqa: BLE001 — provider boundary
        logger.error("[brain] OpenAI direct failed too: %s", exc)
        return None
