"""Routing signals are not actions, and a refusal has to say why.

From the owner's log, mid-confirmation. He had said "أي والله متأكد":

    [Tool] pending_confirm | args=[]
    [voice_ws] tool pending_confirm did not run:

Nothing after the colon.

Two separate faults met there. `pending_confirm` is not a tool — it is a signal
that tells the *text* pipeline which branch to take, and its handler is a stub
whose own comment says it is never called, because `execute_node` filters these
out by name before dispatch. The voice path had no such filter, so it dispatched
the stub, which declined.

And the refusal printed `reply`, which for that stub is the empty string. So the
log proved something had gone wrong and hid what — the same shape as the broker
disconnect that logged its flags instead of its reason.

The model was then handed "[فشل التنفيذ] الأداة ما اشتغلت" for an answer the
user had in fact given. That is a bad thing to tell a model in the middle of a
confirmation: the next turn is built on the belief that the user's "yes" failed.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-for-voice-tools")

from app.api.voice_ws import tools as voice_tools  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


def test_every_meta_tool_is_recognised_as_a_routing_signal():
    """The set here must cover what meta_tools declares.

    A meta tool missing from this list is dispatched into a stub that refuses,
    and the model is told its own routing decision failed.
    """
    from app.agent.tools.schemas.meta_tools import META_TOOLS

    declared = {t["name"] for t in META_TOOLS}
    assert declared <= voice_tools._ROUTING_SIGNAL_TOOLS, (
        "these meta tools would be dispatched by voice and refuse: "
        f"{sorted(declared - voice_tools._ROUTING_SIGNAL_TOOLS)}")


def test_the_meta_handler_is_still_the_stub_this_depends_on():
    """If a meta tool ever grows a real handler, this filter would hide it.

    Pinned so that becomes a failing test rather than a feature that silently
    does nothing over voice.
    """
    from app.agent.tools.schemas.meta_tools import META_TOOLS

    for t in META_TOOLS:
        out = t["handler"]({}, None)
        assert out == {"handled": False, "reply": ""}, (
            f"{t['name']} now does something; the voice filter would swallow it")


def test_a_routing_signal_is_answered_rather_than_dispatched():
    src = (_ROOT / "cloud" / "app" / "api" / "voice_ws" / "tools.py").read_text(
        encoding="utf-8")
    body = src[src.index("_ROUTING_SIGNAL_TOOLS = frozenset"):]
    i_check = body.index("if name in _ROUTING_SIGNAL_TOOLS")
    i_dispatch = body.index("dispatcher.dispatch(")
    assert i_check < i_dispatch, (
        "the signal is dispatched before it is recognised")

    guard = body[i_check:i_dispatch]
    assert '"handled": True' in guard, (
        "a routing signal must not be reported to the model as a failure")


def test_a_refusal_logs_more_than_an_empty_reply():
    """`reply` is often empty on a refusal; the reason lives elsewhere. A line
    that proves something failed and hides what is the least useful line a
    failure can write."""
    src = (_ROOT / "cloud" / "app" / "api" / "voice_ws" / "tools.py").read_text(
        encoding="utf-8")
    i = src.index("if not result.get(\"handled\")")
    line = src[i:i + 1600]
    assert 'result.get("error")' in line, "the error field is still discarded"
    assert "keys=" in line, "the shape of the refusal is not logged"


def test_a_tool_that_ran_is_logged_too():
    """"Did the update actually apply?" had no answer: the call was printed and
    the outcome never was."""
    src = (_ROOT / "cloud" / "app" / "api" / "voice_ws" / "tools.py").read_text(
        encoding="utf-8")
    assert "tool %s ok:" in src
