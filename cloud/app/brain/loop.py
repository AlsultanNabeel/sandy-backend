"""One turn of the new agent: model -> tool calls -> results -> model, until text.

`run_turn` takes `run_graph`'s arguments and returns the few state keys its
callers read (`final_response`, `pending_state`, `execution_result`), so the
chat route swaps one function for the other behind the flag.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.agent.fast_path import try_fast_route
from app.agent.graph.graph import _stm_load, _stm_save, recent_turns_for_user
from app.agent.nodes.execute import _get_stream_hooks
from app.brain import confirm, context, model, tools
from app.brain.ctx import TurnCtx
from app.utils.tenant_version import turn_scope

logger = logging.getLogger(__name__)

MAX_STEPS = 6
ERROR_REPLY = "حصل خطأ، حاول مرة ثانية."
GAVE_UP_REPLY = "ما قدرت أكمّل هالطلب، جرّب تحكيه بطريقة تانية."


def _history(thread_id: str, user_id: str):
    """(this thread's turns, the turns the prompt sees) — same merge as run_graph."""
    threads: Dict[str, List[Dict[str, Any]]] = {}
    cross = recent_turns_for_user(user_id, limit=6, threads_out=threads)
    key = f"{thread_id}:{user_id}"
    own = threads[key] if key in threads else _stm_load(thread_id, user_id)
    seen = {(m.get("role"), m.get("content")) for m in own}
    extra = [m for m in cross if (m.get("role"), m.get("content")) not in seen]
    return own, extra + own


def _for_model(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


def _assistant_msg(reply: model.Reply) -> Dict[str, Any]:
    return {"role": "assistant", "content": reply.text or None, "tool_calls": [
        {"id": c.id, "type": "function",
         "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
        for c in reply.tool_calls]}


def _run_loop(messages: List[Dict[str, Any]], ctx: TurnCtx,
              complete: Callable) -> Dict[str, Any]:
    """{"text", "pending", "tools"} after at most MAX_STEPS model calls."""
    hooks = _get_stream_hooks()
    on_text = None
    if hooks:
        hooks[0]()
        on_text = hooks[1]
    used: List[str] = []
    replies: List[str] = []
    specs = tools.openai_tools()
    for _ in range(MAX_STEPS):
        reply = complete(messages, specs, on_text=on_text)
        if reply is None:
            return {"text": ERROR_REPLY, "pending": None, "tools": used, "error": True}
        if not reply.tool_calls:
            return {"text": reply.text or GAVE_UP_REPLY, "pending": None, "tools": used}
        messages.append(_assistant_msg(reply))
        pending = None
        for call in reply.tool_calls:
            used.append(call.name)
            result = tools.execute(call.name, call.args, ctx)
            if result.get("needs_confirmation") and pending is None:
                pending = confirm.hold(call.name, call.args, result["summary"])
            if result.get("reply"):
                replies.append(result["reply"])
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": _for_model(result)})
        if pending is not None:
            # Deterministic question, no second call: the model cannot talk past it.
            return {"text": confirm.question(pending["summary"]), "pending": pending,
                    "tools": used}
    logger.warning("[brain] step cap (%d) reached; tools=%s", MAX_STEPS, used)
    return {"text": "\n".join(replies) or GAVE_UP_REPLY, "pending": None, "tools": used}


def _resolve_pending(pending: Dict[str, Any], message: str,
                     ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """The turn's outcome when the message answers a held action, else None."""
    said = confirm.answer(message)
    if said == "no":
        return {"text": confirm.CANCELLED_REPLY, "pending": None, "tools": []}
    if said == "yes":
        result = confirm.run_held(pending, ctx)
        text = result.get("reply") or ("تم ✅" if result.get("ok") else GAVE_UP_REPLY)
        return {"text": text, "pending": None, "tools": [pending.get("tool", "")]}
    return None


def _fast(message: str, ctx: TurnCtx, image_state) -> Optional[Dict[str, Any]]:
    fc = try_fast_route({"message": message, "pending_state": None,
                         "image_state": image_state})
    if fc is None:
        return None
    result = tools.execute(fc["name"], fc.get("args") or {}, ctx)
    return {"text": result.get("reply") or GAVE_UP_REPLY, "pending": None,
            "tools": [fc["name"]], "fast": True}


def run_turn(message: str, user_id: str, chat_id: str, *,
             pending_state: Optional[Dict[str, Any]] = None, source: str = "user",
             image_state: Optional[Dict[str, Any]] = None,
             conversation_id: Optional[str] = None,
             complete: Optional[Callable] = None) -> Dict[str, Any]:
    with turn_scope():
        return _run_turn(message, user_id, chat_id, pending_state=pending_state,
                         source=source, image_state=image_state,
                         conversation_id=conversation_id,
                         complete=complete or model.complete)


def _run_turn(message, user_id, chat_id, *, pending_state, source, image_state,
              conversation_id, complete) -> Dict[str, Any]:
    t0 = time.perf_counter()
    thread_id = str(conversation_id or chat_id)
    ctx = TurnCtx(user_id=str(user_id), message=message,
                  source="voice" if source == "voice" else "chat", image_state=image_state)
    held = confirm.live(pending_state)
    outcome = _resolve_pending(held, message, ctx) if held else None
    own, history = _history(thread_id, user_id)
    if outcome is None:
        outcome = _fast(message, ctx, image_state)
    if outcome is None:
        try:
            messages = [{"role": "system",
                         "content": context.build_system(user_id, message, history)},
                        *context.history_messages(history),
                        {"role": "user", "content": message}]
            outcome = _run_loop(messages, ctx, complete)
        except Exception:  # noqa: BLE001 — the request boundary: answer, never 500
            logger.exception("[brain] turn failed")
            outcome = {"text": ERROR_REPLY, "pending": None, "tools": [], "error": True}

    text = outcome["text"]
    logger.info("[turn] %.0fms total — brain%s tools=%s",
                (time.perf_counter() - t0) * 1000, " (fast)" if outcome.get("fast") else "",
                outcome["tools"])
    _stm_save(thread_id, user_id, message, text, prior_history=own,
              via="شات التطبيق" if source == "web" else (source or ""))
    return {
        "message": message, "user_id": user_id, "chat_id": chat_id,
        "final_response": text,
        "pending_state": outcome["pending"],
        "routed_by": "fast_path" if outcome.get("fast") else "brain",
        "tools_used": outcome["tools"],
        "error": "brain turn failed" if outcome.get("error") else None,
        "execution_result": {"handled": True, "reply": text,
                             "image_bytes": ctx.artifacts.get("image_bytes"),
                             "caption": ctx.artifacts.get("caption", "")},
    }
