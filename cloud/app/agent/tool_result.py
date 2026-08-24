"""The two-flag contract every tool and handler result speaks.

``handled`` means *"this handler owns the turn and here is its answer"*.
``ok`` means *"the change the user asked for actually happened"*.

They are not the same thing, and for a long time only ``handled`` existed, so
every reader that wanted the second question had to ask the first one. Three
features were built on that mistake:

* the task adapter overwrote a refusal with a success sentence — a guest was
  told ``سجّلتها ✅ 3 مهام`` for three tasks that were never written;
* :mod:`app.agent.tool_health` recorded every refusal as a success, which is
  why the health monitor had never once flagged a tool;
* the graph appended ``" ✅"`` to ``سجّل دخولك عشان أقدر أساعدك بهالطلب 😊``;
* and on the voice path a refusal reached Gemini as ordinary text, so she
  confirmed work the backend had declined to do.

A refusal is therefore ``{"handled": True, "ok": False, "reply": …}``: the
handler ran, it has an answer, and the answer is no.

**When to set ``ok=False``.** When the user's request did not take effect — a
refusal, a not-found target of a change, an input the handler gave up on, a
failed write, or a no-op because there was nothing to act on.

**When not to.** A read or a search that legitimately found nothing has
answered the question, and a confirmation prompt or a clarifying question that
stores a pending is the handler doing its job mid-flow. Both keep the default.

``ok`` is optional on purpose. A result that omits it reads as ``ok == handled``
— which is what every site meant before the split — so a handler nobody has
revisited keeps its old behaviour instead of silently reporting failure.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


def result_ok(result: Optional[Mapping[str, Any]]) -> bool:
    """Did the change the caller asked for actually happen?

    Falls back to ``handled`` when a result carries no ``ok``, so this is safe
    to call on any handler result, migrated or not.
    """
    if not isinstance(result, Mapping):
        return False
    if "ok" in result:
        return bool(result.get("ok"))
    return bool(result.get("handled"))


def result_failed(result: Optional[Mapping[str, Any]]) -> bool:
    """Did the *tool* break, as opposed to correctly answering no?

    This is a third question, and conflating it with ``ok`` is a live trap.
    :mod:`app.agent.tool_health` asks whether a tool is flaky right now, and a
    refusal is not flakiness — it is the tool working. Scoring refusals as
    failures makes the monitor fire on ordinary use: `_history` is keyed by tool
    name alone and shared by the whole process, so three *different* customers
    each mistyping a shopping item once is enough to cross the degradation
    threshold and have the owner told his shopping tool is broken.

    So health reads this, not ``ok``. A tool has failed when it raised, when it
    has no handler, or when it caught its own exception and said so by setting
    ``error`` (see ``executor/dispatch.py::_guard``).

    ``handled: False`` is deliberately **not** a failure here. It is a routing
    signal — ``task_update`` returns it for *"say which field you want changed"*
    — and treating it as breakage marks a perfectly healthy tool degraded after
    three ordinary clarifications. The two genuine ``handled: False`` cases the
    dispatcher produces, an unknown tool and a missing handler, are recorded
    from the dispatcher's own knowledge rather than from the result.
    """
    if not isinstance(result, Mapping):
        return True
    return bool(result.get("error"))
