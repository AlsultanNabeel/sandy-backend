"""The chat on Azure's Responses API (`/openai/v1/responses`), behind the `responses_api`
switch (`utils/flags.py`): the same messages and tools as the chat completions path, turned
into its items here and its answer turned back into a `model.Reply`, so the loop, the checks
and the tools see no difference.

Nothing is kept at Azure (`store: false`). The model's reasoning comes back sealed
(`include: reasoning.encrypted_content`) and is handed back with the tool calls it made on
the next step of the turn (`Reply.items`, kept on the assistant message as `_items`). The
output limit is this path's own (`MAX_OUTPUT_TOKENS`: the reasoning counts against it), the
effort a setting (`SANDY_REASONING_EFFORT`, low by default), and no temperature is sent: a
reasoning model refuses one. When the call fails the step goes on on the chat completions
path (`model.complete`, with its own fallbacks), so the switch never costs a turn.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAIError

from app.brain import model
from app.brain.model import Reply, ToolCall, _parse_args
from app.features import trace_store
from app.integrations import openai_client
from app.utils.circuit_breaker import CircuitOpenError

logger = logging.getLogger(__name__)

SWITCH = "responses_api"
# Reasoning and answer together; the chat completions path keeps `model.MAX_TOKENS`.
MAX_OUTPUT_TOKENS = 2000


def _tools(specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chat completions' ``{type, function: {...}}`` as the Responses API's flat tools."""
    out = []
    for spec in specs or []:
        fn = spec.get("function") or {}
        out.append({"type": "function", "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}}})
    return out


def _content(content: Any) -> Any:
    """A message's content: text as it is, a chat completions part list as input parts."""
    if not isinstance(content, list):
        return content or ""
    parts = []
    for p in content:
        if p.get("type") == "text":
            parts.append({"type": "input_text", "text": p.get("text", "")})
        elif p.get("type") == "image_url":
            parts.append({"type": "input_image",
                          "image_url": (p.get("image_url") or {}).get("url", "")})
    return parts


def _items(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The turn's chat completions messages as Responses input items."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""),
                        "output": m.get("content") or ""})
        elif role == "assistant" and m.get("_items"):
            # What this path answered, sealed reasoning included, handed back as it came.
            out += m["_items"]
        elif role == "assistant" and m.get("tool_calls"):
            if m.get("content"):
                out.append({"role": "assistant", "content": m["content"]})
            out += [{"type": "function_call", "call_id": c.get("id", ""),
                     "name": (c.get("function") or {}).get("name", ""),
                     "arguments": (c.get("function") or {}).get("arguments") or "{}"}
                    for c in m["tool_calls"]]
        else:
            out.append({"role": role, "content": _content(m.get("content"))})
    return out


def _reply(response: Any) -> Reply:
    text, calls, items = "", [], []
    for item in getattr(response, "output", None) or []:
        kind = getattr(item, "type", "")
        if kind == "message":
            text += "".join(getattr(p, "text", "") or "" for p in getattr(item, "content", None) or []
                            if getattr(p, "type", "") == "output_text")
        elif kind == "function_call":
            calls.append(ToolCall(item.call_id, item.name, _parse_args(item.arguments)))
        items.append(item.model_dump(exclude_none=True))
    return Reply(text=text.strip(), tool_calls=calls, items=items)


def _note_usage(response: Any, t0: float) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
    thought = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0
    trace_store.note_model_call(
        "azure", str(getattr(response, "model", "") or ""),
        tokens_in=getattr(usage, "input_tokens", 0) or 0,
        tokens_out=getattr(usage, "output_tokens", 0) or 0,
        tokens_cached=cached, tokens_reasoning=thought, ms=(time.perf_counter() - t0) * 1000)


def _streamed(events: Any, on_text: Callable[[str], None]) -> Any:
    """The finished response of a stream; its text deltas go out as they arrive (cumulative)."""
    text, done = "", None
    for event in events:
        kind = getattr(event, "type", "")
        if kind == "response.output_text.delta":
            text += getattr(event, "delta", "") or ""
            on_text(text)
        elif kind == "response.completed":
            done = event.response
        elif kind in ("response.failed", "response.incomplete", "error"):
            raise RuntimeError(f"[responses] stream ended: {kind}")
    if done is None:
        raise RuntimeError("[responses] stream ended without a response")
    return done


def _call(messages, tools, on_text):
    from app.config import SANDY_REASONING_EFFORT, SANDY_RESPONSES_DEPLOYMENT

    kwargs: Dict[str, Any] = {
        "model": SANDY_RESPONSES_DEPLOYMENT, "input": _items(messages),
        "reasoning": {"effort": SANDY_REASONING_EFFORT}, "store": False,
        "include": ["reasoning.encrypted_content"], "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    if tools:
        kwargs["tools"] = _tools(tools)
    t0 = time.perf_counter()
    if on_text is not None:
        response = _streamed(openai_client.create_response(stream=True, **kwargs), on_text)
    else:
        response = openai_client.create_response(**kwargs)
    _note_usage(response, t0)
    return _reply(response)


def complete(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]],
             on_text: Optional[Callable[[str], None]] = None) -> Optional[Reply]:
    """One model step on the Responses API; on the chat completions path when it fails."""
    if openai_client.responses_client() is None:
        return model.complete(messages, tools, on_text)
    try:
        return _call(messages, tools, on_text)
    except (OpenAIError, CircuitOpenError, RuntimeError, ValueError) as exc:
        logger.warning("[brain] Responses API failed, on chat completions instead: %s", exc)
        return model.complete(messages, tools, on_text)
