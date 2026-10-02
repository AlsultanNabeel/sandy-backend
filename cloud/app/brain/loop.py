"""One chat turn: model -> tool calls -> results -> model, until text.

A held action is resolved first, then the fast path, then at most MAX_STEPS
model calls. `run_turn` returns what the chat routes read: the reply, the pending
to store for the next turn, and any image a tool made.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.brain import confirm, context, future, model, stm, tools
from app.brain.fast_path import try_fast_route
from app.brain.ctx import TurnCtx
from app.utils.tenant_version import turn_scope

logger = logging.getLogger(__name__)

MAX_STEPS = 6
ERROR_REPLY = "حصل خطأ، حاول مرة ثانية."
GAVE_UP_REPLY = "ما قدرت أكمّل هالطلب، جرّب تحكيه بطريقة تانية."


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
    hooks = model.stream_hooks()
    on_text = None
    if hooks:
        hooks[0]()
        on_text = hooks[1]
    used: List[str] = []
    replies: List[str] = []
    specs = tools.openai_tools()
    on_step = model.step_hook()
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
            if on_step:
                on_step(call.name)
            result = tools.execute(call.name, call.args, ctx)
            if pending is None:
                pending = _hold_if_asked(call.name, call.args, result)
            if result.get("reply"):
                replies.append(result["reply"])
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": _for_model(result)})
        if pending is not None:
            # Deterministic question, no second call: the model cannot talk past it.
            return {"text": _ask(pending), "pending": pending, "tools": used}
    logger.warning("[brain] step cap (%d) reached; tools=%s", MAX_STEPS, used)
    return {"text": "\n".join(replies) or GAVE_UP_REPLY, "pending": None, "tools": used}


def _hold_if_asked(name: str, args: Dict[str, Any],
                   result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A pending when the tool is waiting on the user (a yes, or which one), else None."""
    if result.get("needs_confirmation"):
        return confirm.hold(name, args, result["summary"])
    if result.get("needs_choice"):
        return confirm.hold_choice(name, args, result["candidates"])
    return None


def _ask(pending: Dict[str, Any]) -> str:
    if pending.get("action") == confirm.CHOOSE:
        return confirm.choice_question(pending["candidates"])
    return confirm.question(pending["summary"])


def _resolve_choice(pending: Dict[str, Any], message: str,
                    ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    if confirm.answer(message) == "no":
        return {"text": confirm.CANCELLED_REPLY, "pending": None, "tools": []}
    ids = confirm.pick(message, pending.get("candidates") or [])
    if ids is None:
        return None
    args = {k: v for k, v in (pending.get("args") or {}).items() if k != "match_text"}
    if len(ids) == 1:
        args["id"] = ids[0]
    else:
        args["match_text"] = (pending.get("args") or {}).get("match_text", "")
        args["all_matching"] = True
    name = pending.get("tool", "")
    result = tools.execute(name, args, ctx)
    held = _hold_if_asked(name, args, result)
    if held is not None:
        return {"text": _ask(held), "pending": held, "tools": [name]}
    return {"text": result.get("reply") or GAVE_UP_REPLY, "pending": None, "tools": [name]}


def _resolve_pending(pending: Dict[str, Any], message: str,
                     ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """The turn's outcome when the message answers a held action, else None."""
    if pending.get("action") == confirm.CHOOSE:
        return _resolve_choice(pending, message, ctx)
    said = confirm.answer(message)
    if said == "no":
        return {"text": confirm.CANCELLED_REPLY, "pending": None, "tools": []}
    if said == "yes":
        result = confirm.run_held(pending, ctx)
        text = result.get("reply") or ("تم ✅" if result.get("ok") else GAVE_UP_REPLY)
        return {"text": text, "pending": None, "tools": [pending.get("tool", "")]}
    return None


def _fast(message: str, ctx: TurnCtx, image_state) -> Optional[Dict[str, Any]]:
    fc = try_fast_route(message, image_state=image_state)
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
    own, history = stm.history(thread_id, user_id)
    if outcome is None:
        outcome = _fast(message, ctx, image_state)
    if outcome is None:
        due = None
        try:
            system = context.build_system(user_id, message, history, spoken=ctx.source == "voice")
            due = future.due_context()
            if due:
                system += "\n\n" + due[0]
            messages = [{"role": "system", "content": system},
                        *context.history_messages(history),
                        {"role": "user", "content": message}]
            outcome = _run_loop(messages, ctx, complete)
        except Exception:  # noqa: BLE001 — the request boundary: answer, never 500
            logger.exception("[brain] turn failed")
            outcome = {"text": ERROR_REPLY, "pending": None, "tools": [], "error": True}
        if due and not outcome.get("error"):
            # Delivered only once a real reply carries it.
            future.mark_delivered(due[1])

    text = outcome["text"]
    logger.info("[turn] %.0fms total — brain%s tools=%s",
                (time.perf_counter() - t0) * 1000, " (fast)" if outcome.get("fast") else "",
                outcome["tools"])
    stm.save(thread_id, user_id, message, text, prior_history=own,
             via="شات التطبيق" if source == "web" else (source or ""), source=ctx.source)
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
