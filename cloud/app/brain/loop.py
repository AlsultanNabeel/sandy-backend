"""One chat turn: model -> tool calls -> results -> model, until text.

A held action is resolved first, then the fast path, then at most MAX_STEPS
model calls. `run_turn` returns what the chat routes read: the reply, the pending
to store for the next turn, and any image a tool made.
"""

from __future__ import annotations

import base64
import contextvars
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.blocks import _base as blocks_base
from app.brain import confirm, context, future, model, stm, stops, tools
from app.brain.fast_path import try_fast_route
from app.brain.ctx import TurnCtx
from app.utils.tenant_version import turn_scope

logger = logging.getLogger(__name__)

MAX_STEPS = 6
ERROR_REPLY = "حصل خطأ، حاول مرة ثانية."
GAVE_UP_REPLY = "ما قدرت أكمّل هالطلب، جرّب تحكيه بطريقة تانية."
# Tools whose `reply` is already the answer: when every call of the turn is one of these
# and worked, that reply goes out with no second model call to restate it.
ANSWER_TOOLS = frozenset({"device_control", "scene_apply", "room_restore", "image"})
# Slow tools that touch nothing another call reads: several in one step run side by side.
# Not `image`: a turn draws one, and two at once could both find none drawn yet.
SIDE_BY_SIDE = frozenset({"web_search", "weather", "recall", "summarize", "device_state"})


def _for_model(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


def _assistant_msg(reply: model.Reply) -> Dict[str, Any]:
    return {"role": "assistant", "content": reply.text or None, "tool_calls": [
        {"id": c.id, "type": "function",
         "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
        for c in reply.tool_calls]}


# What the model reads for a held call: the system asks, the model goes on with the rest.
HELD_NOTE = ("مستنّي تأكيده؛ النظام بيسأله بآخر الرد. ما تسأليه انتِ، وما تحكي إنه انعمل، "
             "وما تعيدي هالأداة، وكمّلي باقي طلبه إذا في.")


def _run_loop(messages: List[Dict[str, Any]], ctx: TurnCtx,
              complete: Callable, stopped: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """{"text", "pending", "tools"} after at most MAX_STEPS model calls. Once the app
    stops the reply (`stopped`), no further tool or model call runs.

    A delete that waits for a yes does not end the turn: the rest of the request still
    runs, every held action joins one question, and the reply is the model's answer (or,
    with none, what the tools did) plus that question, which is ours, never the model's."""
    hooks = model.stream_hooks()
    on_text = None
    if hooks:
        hooks[0]()
        on_text = hooks[1]
    used: List[str] = []
    replies: List[str] = []
    held: Optional[Dict[str, Any]] = None
    specs = tools.openai_tools()
    on_step = model.step_hook()
    for step in range(MAX_STEPS):
        if step and stopped():
            return {"text": "\n".join(replies), "pending": None, "tools": used, "stopped": True}
        # Once something is held the reply is ours, so nothing of the model's is streamed.
        reply = complete(messages, specs, on_text=None if held else on_text)
        if reply is None:
            if held is not None:
                return _settled(replies, held, used)
            return {"text": ERROR_REPLY, "pending": None, "tools": used, "error": True}
        if not reply.tool_calls:
            if held is not None:
                # The model's answer to the rest of the line stays (it has the tools'
                # results), then the question; its own words replace the tools' replies.
                return _settled([reply.text] if reply.text else replies, held, used)
            return {"text": reply.text or GAVE_UP_REPLY, "pending": None, "tools": used}
        messages.append(_assistant_msg(reply))
        early = _run_side_by_side(reply.tool_calls, ctx)
        all_answered = True
        for call in reply.tool_calls:
            if stopped():
                return {"text": "\n".join(replies), "pending": None, "tools": used, "stopped": True}
            used.append(call.name)
            if on_step:
                on_step(call.name)
            result = early.get(call.id) or tools.execute(call.name, call.args, ctx)
            all_answered &= call.name in ANSWER_TOOLS and bool(result.get("ok")) and bool(result.get("reply"))
            held, waiting = _hold(held, call.name, call.args, result)
            if waiting:
                result = {"ok": False, "held": True, "note": HELD_NOTE}
            elif result.get("reply"):
                replies.append(result["reply"])
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": _for_model(result)})
        if held is None and all_answered and set(used) <= ANSWER_TOOLS:
            return {"text": "\n".join(replies), "pending": None, "tools": used}
    logger.warning("[brain] step cap (%d) reached; tools=%s", MAX_STEPS, used)
    return _settled(replies, held, used)


def _run_side_by_side(calls, ctx: TurnCtx) -> Dict[str, Dict[str, Any]]:
    """{call id: result} for this step's slow independent calls, run at once when there
    are two or more; every other call runs in order as usual. Each thread gets the turn's
    context (tenant, undo journal)."""
    slow = [c for c in calls if c.name in SIDE_BY_SIDE]
    if len(slow) < 2:
        return {}
    with ThreadPoolExecutor(max_workers=len(slow)) as pool:
        futures = {c.id: pool.submit(contextvars.copy_context().run,
                                     tools.execute, c.name, c.args, ctx) for c in slow}
    return {cid: f.result() for cid, f in futures.items()}


def _hold(held: Optional[Dict[str, Any]], name: str, args: Dict[str, Any],
          result: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the turn's pending, whether this call joined it). Every action waiting for a yes
    joins one question; a «which one?» is held only when nothing else is."""
    if result.get("needs_confirmation") and (held is None or held.get("action") != confirm.CHOOSE):
        return confirm.with_step(held, name, args, result["summary"]), True
    if result.get("needs_choice") and held is None:
        return confirm.hold_choice(name, args, result["candidates"]), True
    return held, False


def _ask(pending: Dict[str, Any]) -> str:
    if pending.get("action") == confirm.CHOOSE:
        return confirm.choice_question(pending["candidates"])
    return confirm.question(pending["summary"])


def _settled(replies: List[str], held: Optional[Dict[str, Any]],
             used: List[str]) -> Dict[str, Any]:
    """What was done, then the question when something waits for the user. `done` is
    the first part alone."""
    done = "\n".join(replies)
    if held is None:
        return {"text": done or GAVE_UP_REPLY, "pending": None, "tools": used, "done": done}
    return {"text": "\n".join([*replies, _ask(held)]), "pending": held, "tools": used,
            "done": done}


def _rest_note(settled: str) -> str:
    return (f"[جوابه على السؤال انحسب: {settled}. نفّذي بس الباقي من رسالته، وما تعيدي "
            "هالإشي ولا تحكي عنه.]")


def _resolve_choice(pending: Dict[str, Any], message: str,
                    ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """The turn's outcome when the message picks from «which one?», else None. The pick is
    read from the opening only; a request after it («التانية وضيفي خبز») goes to the model."""
    said, rest = confirm.read(message)
    if said == "no":
        outcome = {"text": confirm.CANCELLED_REPLY, "pending": None, "tools": []}
        if rest:
            outcome["rest"] = _rest_note("قال لأ على «أي وحدة؟»، فما انعمل")
        return outcome
    ids, rest = confirm.pick(message, pending.get("candidates") or [])
    if ids is None:
        return None
    name = pending.get("tool", "")
    base = {k: v for k, v in (pending.get("args") or {}).items()
            if k not in ("match_text", "all_matching")}
    held, replies = None, []
    for row_id in ids:
        args = {**base, "id": row_id}
        result = tools.execute(name, args, ctx)
        held, waiting = _hold(held, name, args, result)
        if not waiting and result.get("reply"):
            replies.append(result["reply"])
    outcome = _settled(replies, held, [name])
    if rest:
        outcome["rest"] = _rest_note(f"اختار، والنتيجة: {outcome['text']}")
    return outcome


def _resolve_pending(pending: Dict[str, Any], message: str,
                     ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """The turn's outcome when the message answers a held action, else None. When a new
    request follows the answer («اه وضيفي خبز»), `rest` tells the model what the answer
    already settled, and the model does the rest."""
    if pending.get("action") == confirm.CHOOSE:
        return _resolve_choice(pending, message, ctx)
    said, rest = confirm.read(message, pending)
    if said == "other":
        return None
    summary = pending.get("summary", "")
    used = [s.get("tool", "") for s in pending.get("steps") or []]
    if said == "no":
        outcome = {"text": confirm.CANCELLED_REPLY, "pending": None, "tools": []}
        settled = f"قال لأ على «{summary}»، فما انعمل"
    else:
        result = confirm.run_held(pending, ctx)
        text = result.get("reply") or ("تم ✅" if result.get("ok") else GAVE_UP_REPLY)
        outcome = {"text": text, "pending": None, "tools": used}
        settled = f"قال اه على «{summary}»، والنتيجة: {text}"
    if rest:
        outcome["rest"] = _rest_note(settled)
    return outcome


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
             attachments: Optional[List[Dict[str, Any]]] = None,
             complete: Optional[Callable] = None) -> Dict[str, Any]:
    with turn_scope():
        return _run_turn(message, user_id, chat_id, pending_state=pending_state,
                         source=source, image_state=image_state,
                         conversation_id=conversation_id, attachments=attachments or [],
                         complete=complete or model.complete)


def _user_content(message: str, attachments: List[Dict[str, Any]]) -> Any:
    """The user's turn for the model: plain text, or text with the photos to look at and
    the documents' words to read."""
    if not attachments:
        return message
    text = message or "شوفي المرفق."
    for a in attachments:
        if a.get("kind") == "file":
            text += f"\n\n[مرفق «{a.get('name', '')}»]:\n{a.get('text', '')}"
    parts: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    for a in attachments:
        if a.get("kind") == "image":
            data = base64.b64encode(bytes(a.get("data") or b"")).decode()
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{a.get('mime') or 'image/jpeg'};base64,{data}"}})
    return parts if len(parts) > 1 else text


def _remembered_line(message: str, attachments: List[Dict[str, Any]]) -> str:
    """The user's line as memory keeps it: the words, and which attachments came with them."""
    marks = " ".join(f"[{'صورة' if a.get('kind') == 'image' else 'ملف'}: {a.get('name', '')}]"
                     for a in attachments)
    return (message + " " + marks).strip()


def _run_turn(message, user_id, chat_id, *, pending_state, source, image_state,
              conversation_id, attachments, complete) -> Dict[str, Any]:
    t0 = time.perf_counter()
    began = datetime.now(timezone.utc)
    thread_id = str(conversation_id or chat_id)
    ctx = TurnCtx(user_id=str(user_id), message=message, thread_id=thread_id,
                  source="voice" if source == "voice" else "chat", image_state=image_state)
    held = confirm.live(pending_state)
    _, history = stm.history(thread_id, user_id)
    # Everything the turn writes is journaled, a confirmed «yes» included, so a rewritten
    # or edited reply can take it all back.
    with blocks_base.journal() as effects:
        resolved = _resolve_pending(held, message, ctx) if held else None
        settled = resolved if resolved is not None and resolved.get("rest") else None
        outcome = _answer(None if settled else resolved, message, ctx, image_state, user_id,
                          thread_id, history, complete, attachments, began,
                          note=settled["rest"] if settled else "")
        if settled:
            # A «no» says nothing of its own here: the model's reply is the answer. A pick
            # that still waits for a yes asks it last, after the rest was answered.
            waiting = settled.get("pending")
            first = (settled["done"] if waiting else settled["text"]) if settled["tools"] else ""
            text = "\n".join(t for t in (first, outcome["text"]) if t)
            pending = outcome["pending"]
            if waiting is not None and pending is None:
                text, pending = f"{text}\n{_ask(waiting)}", waiting
            outcome = {**outcome, "text": text, "pending": pending,
                       "tools": settled["tools"] + outcome["tools"]}
        elif (held and resolved is None and outcome["pending"] is None
              and not outcome.get("error") and not outcome.get("stopped")):
            # Neither yes nor no: the message was answered, and the question is asked once more.
            again = confirm.asked_again(held)
            if again is not None:
                outcome = {**outcome, "text": f"{outcome['text']}\n{_ask(again)}", "pending": again}

    # Stopped from the app: memory keeps what was shown, marked as cut.
    shown = stops.take(user_id, thread_id, since=began)
    if not (outcome.get("error") or outcome.get("stopped") or shown is not None):
        # Due messages to your future self ride on a reply that went out whole.
        due = future.due()
        if due:
            outcome = {**outcome, "text": f"{outcome['text']}\n\n{due[0]}"}
            future.mark_delivered(due[1])
    text = outcome["text"]
    remembered = stops.cut(shown) if shown is not None else text
    logger.info("[turn] %.0fms total — brain%s tools=%s",
                (time.perf_counter() - t0) * 1000, " (fast)" if outcome.get("fast") else "",
                outcome["tools"])
    stm.save(thread_id, user_id, _remembered_line(message, attachments), remembered,
             via="شات التطبيق" if source == "web" else (source or ""), source=ctx.source,
             effects=effects)
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


def _answer(outcome, message, ctx, image_state, user_id, thread_id, history, complete,
            attachments=(), began=None, note=""):
    """The held confirmation's outcome, else the fast path's, else the model loop's.
    A line with attachments, or with `note` (what an answer already settled), always goes
    to the model."""
    if outcome is None and not attachments and not note:
        outcome = _fast(message, ctx, image_state)
    if outcome is None:
        try:
            system = context.build_system(user_id, message, history, spoken=ctx.source == "voice",
                                          thread_id=thread_id)
            if note:
                system += "\n\n" + note
            messages = [{"role": "system", "content": system},
                        *context.history_messages(history),
                        {"role": "user", "content": _user_content(message, list(attachments))}]
            outcome = _run_loop(messages, ctx, complete,
                                stopped=lambda: stops.requested(user_id, thread_id, since=began))
        except Exception:  # noqa: BLE001 — the request boundary: answer, never 500
            logger.exception("[brain] turn failed")
            outcome = {"text": ERROR_REPLY, "pending": None, "tools": [], "error": True}
    return outcome
