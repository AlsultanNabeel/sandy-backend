"""A task at its time (`blocks/tasks.py`, fired by `services/schedule_runner.py`): the code
checks first, the model only when something changed, one review before anything is sent,
and the result goes out through `notify.deliver`. Never a word aloud.

1. The probe: one read tool with the task's fixed arguments (`READ_TOOLS`), run by the code;
   a web search gives its raw results (`research.web_results`), never a model's summary. Its
   fingerprint (of what the data says: what moves by itself between reads, a device's last
   seen or a period's end, and the order of a list are left out; of a web search, each
   result's title and link alone) is the same as the last
   run's: the run ends there, with no model call and no message.
2. The model, on what changed, with the task's own tools only (within `ALLOWED`), at most
   `MAX_STEPS` steps: it answers what is worth telling him, or `NOTHING`.
3. The review: the model reads that once against the task and the data, and answers it as it
   should be sent, or `NOTHING`.
4. `notify.deliver`.

A task that is not urgent sends its model step as an Azure batch when batches are set up
(`brain/batch.py`, off by default), through `background` like every other model call: the run
submits it, and a later run collects the answer and goes on to the review. A batch that failed,
or could not be submitted, goes the ordinary way at once and is no failure of the task. A run that fails counts; `FAILURES_TO_STOP` in a row pause the task and say so. Both model
steps go through `background.call` ("task", "task_review": the deployment per step from the
settings), in one background trace row per run that names its task (`task_id`), each call
marked with its step (`what`: "task", "task_review"). Only an account with the `tasks` switch on
runs its tasks.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAIError
from pymongo.errors import PyMongoError

from app import notify
from app.blocks import tasks
from app.brain import background, lang, task_diff, tools
from app.brain.ctx import TurnCtx
from app.brain.model import _from_message
from app.features import trace_store

logger = logging.getLogger(__name__)

SWITCH, READ_TOOLS, ALLOWED = tasks.SWITCH, tasks.READ_TOOLS, tasks.ALLOWED
NOTHING = "NOTHING"
MAX_STEPS = 4
FAILURES_TO_STOP = 3
# What a batch's submit or answer raises (Azure's client, a failed or expired job, its file read).
_BATCH_ERRORS = (OpenAIError, RuntimeError, OSError, ValueError, KeyError)

_THINK = (
    "You are Sandy, doing on your own a task the user set up; there is no conversation. "
    "The task, in his own words: {instructions}\n"
    "Worth telling him: {notify_when}\n"
    "What you told him last time: {last}\n"
    "Below is exactly what changed since the last check, computed by code: rows added, removed "
    "or changed, numbers before and after, paragraphs added or removed. Explain only that; "
    "never name anything that is not in it. Use your tools only if you need more. If nothing in "
    "it is worth telling him, answer exactly NOTHING. Otherwise answer the message to send him: "
    "short, in {language}, names and his words kept as they are. Never say how or when he "
    "is told; the way it reaches him is set apart. Only what changed.")
_REVIEW = (
    "You check a message before it is sent to the user. The task, in his own words: "
    "{instructions}\nWorth telling him: {notify_when}\nRead the message against the task and "
    "what changed. If it is wrong, names anything that did not change, or says how or when he "
    "is told, fix it; if it is not worth sending, answer exactly NOTHING. "
    "Otherwise answer the message as it should be sent, in {language}, and nothing else.")


def _id(doc: Dict[str, Any]) -> str:
    """The row's id: `_id` as the runner reads it, `id` as `schedules.get` gives it."""
    return str(doc.get("_id") or doc.get("id") or "")


def _stable(found: Any) -> Any:
    """``found`` without what moves by itself (`task_diff.MOVES_BY_ITSELF`), its lists in one
    order."""
    if isinstance(found, dict):
        return {k: _stable(v) for k, v in found.items() if k not in task_diff.MOVES_BY_ITSELF}
    if isinstance(found, list):
        items = [_stable(v) for v in found]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False,
                                                      default=str))
    return found


# Of a web search's results, what stays put between two searches of the same page; the snippet
# under each moves («posted 2 minutes ago») and is shown to the model, never compared.
_WEB_KEPT = ("title", "url")


def fingerprint(found: Any, tool: str = "") -> str:
    """What the data says, not when it was read (`_stable`); a web search's results by their
    title and link alone, in one order."""
    if tool == "web_search" and isinstance(found, dict):
        found = sorted({tuple(str(r.get(k) or "") for k in _WEB_KEPT)
                        for r in found.get("results") or [] if isinstance(r, dict)})
    text = json.dumps(_stable(found), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _probe(spec: Dict[str, Any], ctx: TurnCtx) -> Any:
    probe = spec.get("probe") or {}
    tool, args = probe.get("tool"), dict(probe.get("args") or {})
    if tool not in READ_TOOLS:
        raise ValueError(f"a task's check reads only: {tool!r} is not one of {READ_TOOLS}")
    if tool == "web_search":
        from app.features.research import web_results
        return {"results": web_results(str(args.get("query") or ""))}
    result = tools.execute(tool, args, ctx)
    if result.get("broke"):
        raise RuntimeError(f"the check's tool {tool} broke")
    return result


def _kept(found: Any) -> Any:
    """The read as it is kept to compare with the next (JSON, dates as text)."""
    return json.loads(json.dumps(found, ensure_ascii=False, default=str))


def _text(resp: Any) -> str:
    return (resp.choices[0].message.content or "").strip()


def _think(doc: Dict[str, Any], spec: Dict[str, Any], diff: Dict[str, Any], before: Dict[str, Any],
           ctx: TurnCtx, uid: str) -> str:
    """The model's message on what changed, or NOTHING."""
    allowed = [t for t in spec.get("tools") or [] if t in ALLOWED]
    specs = [s for s in tools.openai_tools() if s["function"]["name"] in allowed]
    messages = _think_messages(spec, diff, before)
    for _ in range(MAX_STEPS):
        reply = _from_message(background.call(
            "task", messages, priority=background.SCHEDULED, user_id=uid, tools=specs or None,
            max_tokens=700, temperature=0.3).choices[0].message)
        if not reply.tool_calls:
            return reply.text or NOTHING
        messages.append({"role": "assistant", "content": reply.text or None, "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
            for c in reply.tool_calls]})
        for call in reply.tool_calls:
            result = tools.execute(call.name, call.args, ctx) if call.name in allowed else {
                "ok": False, "error": f"{call.name} is not one of this task's tools"}
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, ensure_ascii=False, default=str)})
    logger.warning("[tasks] task %s reached the step cap", _id(doc))
    return NOTHING


def _think_messages(spec: Dict[str, Any], diff: Dict[str, Any], before: Dict[str, Any]) -> List[Dict[str, Any]]:
    from app.brain.tools_tasks import without_way
    language = "English" if spec.get("lang") == lang.EN else "Arabic"
    return [
        {"role": "system", "content": _THINK.format(
            instructions=without_way(spec.get("instructions", "")),
            notify_when=without_way(spec.get("notify_when", "")),
            last=before.get("last_result") or "nothing yet", language=language)},
        {"role": "user", "content": json.dumps({"changed": task_diff.shown(diff)},
                                               ensure_ascii=False, default=str)}]


def _review(spec: Dict[str, Any], diff: Dict[str, Any], message: str, uid: str) -> str:
    from app.brain.tools_tasks import without_way
    language = "English" if spec.get("lang") == lang.EN else "Arabic"
    return _text(background.call("task_review", [
        {"role": "system", "content": _REVIEW.format(
            instructions=without_way(spec.get("instructions", "")),
            notify_when=without_way(spec.get("notify_when", "")),
            language=language)},
        {"role": "user", "content": json.dumps({"changed": task_diff.shown(diff), "message": message},
                                               ensure_ascii=False, default=str)}],
        priority=background.SCHEDULED, user_id=uid, max_tokens=500, temperature=0)) or NOTHING


def _submitted(doc: Dict[str, Any], spec: Dict[str, Any], diff: Dict[str, Any],
               before: Dict[str, Any]) -> Optional[str]:
    """The batch job its model step went as; None when it goes at once (urgent, batches off,
    or the submit failed)."""
    if spec.get("urgent") or not background.batching(background.SCHEDULED):
        return None
    try:
        return background.call("task", _think_messages(spec, diff, before),
                               priority=background.SCHEDULED, as_batch=True,
                               max_tokens=700, temperature=0.3)
    except _BATCH_ERRORS as exc:  # Azure's boundary: the ordinary way now
        logger.warning("[tasks] task %s: batch not submitted (%s); run at once", _id(doc), exc)
        return None


def _failed(doc: Dict[str, Any], before: Dict[str, Any], error: str) -> None:
    failures = int(before.get("failures") or 0) + 1
    tasks.save_state(_id(doc), {"failures": failures, "last_error": error[:300]})
    logger.warning("[tasks] task %s failed (%d in a row): %s", _id(doc), failures, error)
    if failures >= FAILURES_TO_STOP:
        tasks.pause(_id(doc))
        notify.deliver(_id(doc), str(doc.get("text") or ""),
                       lang.say("task_stopped", title=str(doc.get("text") or "")), lang.current())


def start(task_id: str, uid: str) -> Any:
    """On his yes: one read now, kept as where the task starts (nothing told, no email); what
    it read, or None when the check could not read (its first run at its time starts it)."""
    row = tasks.get(task_id)
    spec = dict((row or {}).get("payload") or {})
    tool = str((spec.get("probe") or {}).get("tool") or "")
    try:
        found = _kept(_probe(spec, TurnCtx(user_id=uid, source="app", whole=True)))
    except (ValueError, RuntimeError, OSError, KeyError, PyMongoError) as exc:  # the task stands
        logger.warning("[tasks] task %s: could not read at its start: %s", task_id, exc)
        return None
    tasks.save_state(task_id, {"fingerprint": fingerprint(found, tool), "last_seen": found,
                               "failures": 0})
    return found


def run(doc: Dict[str, Any], uid: str) -> Optional[str]:
    """One run of a due task, in the current tenant: the id of what it delivered, or None."""
    from app.utils import flags

    if not flags.on(SWITCH, uid):
        return None
    spec = dict(doc.get("payload") or {})
    before = tasks.state(_id(doc))
    # The check reads the whole of what it reads (a list past the chat's thirty rows).
    ctx = TurnCtx(user_id=uid, source="app", whole=True)
    tool = str((spec.get("probe") or {}).get("tool") or "")
    with lang.using(spec.get("lang") or lang.for_user(uid)), \
            trace_store.background(uid, "task", task_id=_id(doc)):
        try:
            message, found, seen, diff, direct = None, None, None, None, False
            if before.get("batch_id"):
                # A batch this task submitted: its answer, once Azure has it.
                try:
                    message = background.collect("task", before["batch_id"], user_id=uid)
                except _BATCH_ERRORS as exc:  # Azure's boundary: the ordinary way now
                    logger.warning("[tasks] task %s: batch %s failed (%s); run at once",
                                   _id(doc), before["batch_id"], exc)
                    direct = True
                else:
                    if message is None:
                        return None
                    found, seen = before.get("batch_found"), before.get("batch_fingerprint")
                    diff = before.get("batch_diff") or {}
                tasks.save_state(_id(doc), {"batch_id": None})
            if message is None:
                found = _kept(_probe(spec, ctx))
                seen = fingerprint(found, tool)
                if before.get("last_seen") is None:
                    # Its first run: where it starts, nothing told.
                    tasks.save_state(_id(doc), {"fingerprint": seen, "last_seen": found, "failures": 0})
                    return None
                if seen == before.get("fingerprint"):
                    tasks.save_state(_id(doc), {"failures": 0})
                    return None
                diff = task_diff.compute(before["last_seen"], found)
                message = NOTHING if task_diff.empty(diff) else task_diff.template(diff)
                if message is None:
                    job = None if direct else _submitted(doc, spec, diff, before)
                    if job:
                        tasks.save_state(_id(doc), {"batch_id": job, "batch_fingerprint": seen,
                                                    "batch_found": found, "batch_diff": diff,
                                                    "failures": 0})
                        return None
                    message = _think(doc, spec, diff, before, ctx, uid)
                    if (message or NOTHING).strip() != NOTHING:
                        message = _review(spec, diff, message, uid)
            elif (message or NOTHING).strip() != NOTHING:
                message = _review(spec, diff, message, uid)
            message = message or NOTHING
        except Exception as exc:  # noqa: BLE001 — a task's run is a background edge: it counts
            _failed(doc, before, f"{type(exc).__name__}: {exc}")
            return None
        if message.strip() != NOTHING and not task_diff.faithful(message, diff, before.get("last_seen"), found):
            # It names what did not change: never sent.
            logger.warning("[tasks] task %s: a message naming what did not change was held back", _id(doc))
            message = NOTHING
        # What it saw now is where the next run compares from, whatever was told.
        state = {"fingerprint": seen, "last_seen": found, "failures": 0}
        if message.strip() == NOTHING:
            tasks.save_state(_id(doc), state)
            return None
        tasks.save_state(_id(doc), {**state, "last_result": message})
        return notify.deliver(_id(doc), str(doc.get("text") or ""), message, lang.current())
