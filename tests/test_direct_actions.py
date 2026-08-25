"""She does it, instead of asking whether to do it.

«خلصت المهمة» used to be answered with «متأكد بدك أعلّم المهمة كمكتملة؟» and a
wait. The owner's objection is the right one: he already said it. A confirmation
earns its cost when the action is hard to undo *and* the machine might have
misheard — marking a task done is neither, it is one word to reverse, and he
does it ten times a day. The question cost a whole extra turn to reach a result
a second sentence could have undone anyway.

**What still asks.** Deleting more than one thing at once. That is a rule about
scale, not danger: deleting one *named* task is direct because the name is the
evidence she heard it right, and «احذف كل المهام» is the one shape where a
misheard sentence costs work nobody can speak back into existence.

`agent/guards.py` is a separate layer and unrelated — it stops the *model* from
picking a destructive tool on its own.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


_TASK = {"id": "task-001", "text": "شراء حليب", "notes": "ملاحظة قديمة"}
_SINGLE = {"status": "single", "tasks": [_TASK], "task": _TASK}


def _call(params):
    from app.agent.executor.dispatch import execute_operational_action
    from app.utils.user_profiles import set_active_user_profile

    set_active_user_profile({"chat_id": "o1", "user_id": "o1", "relation": "user",
                             "permissions": "all", "is_guest": False})
    session: dict = {}
    result = execute_operational_action(
        "task", params,
        user_message="test",
        normalized_user_message="test",
        session=session,
        session_file=None, mongo_db=None, tasks_file=None,
        create_chat_completion_fn=lambda *a, **kw: None,
        save_session_fn=lambda *a, **kw: None,
    )
    return result, session


DIRECT = [
    ("complete", {"action": "complete", "reference": "شراء حليب"}),
    ("uncomplete", {"action": "uncomplete", "reference": "شراء حليب"}),
    ("rename", {"action": "rename", "reference": "شراء حليب", "text": "شراء عصير"}),
    ("append_note", {"action": "append_note", "reference": "شراء حليب",
                     "notes": "ملاحظة"}),
    ("replace_note", {"action": "replace_note", "reference": "شراء حليب",
                      "notes": "ملاحظة جديدة"}),
    ("delete_one", {"action": "delete", "reference": "شراء حليب"}),
]


@pytest.mark.parametrize("label,params", DIRECT, ids=[d[0] for d in DIRECT])
def test_a_named_action_runs_without_a_confirmation_turn(label, params):
    """No pending is left waiting, and the reply is not a question."""
    targets = [
        "app.agent.executor.task_handlers.completion.resolve_task_references_for_write",
        "app.agent.executor.task_handlers.completion.resolve_completed_task_references_for_write",
        "app.agent.executor.task_handlers.notes.resolve_task_reference_for_write",
        "app.agent.executor.task_handlers.deletion.resolve_task_reference_for_write",
    ]
    patches = [patch(t, return_value=_SINGLE) for t in targets]
    for p in patches:
        try:
            p.start()
        except (AttributeError, ModuleNotFoundError):
            pass
    try:
        result, session = _call(params)
    finally:
        for p in patches:
            try:
                p.stop()
            except RuntimeError:
                pass

    assert result.get("handled") is True
    # The executor clears the slot on its way out, so the key may exist holding
    # `None` — what must not exist is something still waiting for an answer.
    assert session.get("pending_action") is None, \
        f"{label} still stores a confirmation and waits"
    assert "متأكد بدك" not in str(result.get("reply", "")), \
        f"{label} still asks before acting"


def test_deleting_everything_still_asks():
    """The one shape where a misheard sentence is not recoverable."""
    from app.agent.executor.task_handlers.deletion import _handle_delete_all

    out = _handle_delete_all(
        session={}, session_file=None, mongo_db=None,
        save_session_fn=lambda *a, **kw: None,
    )
    assert "متأكد بدك أحذف كل المهام" in out["reply"]


def test_run_now_covers_every_action_the_handlers_send_it():
    """A handler that builds an action `run_now` has no executor for would tell
    the user it happened and then do nothing — the failure this whole audit kept
    finding. This walks the handlers and checks the table covers them."""
    import pathlib
    import re

    root = (pathlib.Path(__file__).resolve().parent.parent
            / "cloud/app/agent/executor/task_handlers")
    sent = set()
    for path in root.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"type": "task", "action": "([a-z_]+)"', src):
            sent.add(m.group(1))
        for m in re.finditer(r'"action": \("([a-z_]+)" if .*?\n\s*else "([a-z_]+)"',
                             src, re.S):
            sent.update(m.groups())

    from app.agent.executor.task_handlers import _now

    source = pathlib.Path(_now.__file__).read_text(encoding="utf-8")
    known = set(re.findall(r'^        "([a-z_]+)": _exec_task', source, re.M))
    missing = sorted(sent - known)
    assert not missing, f"handlers send actions run_now cannot execute: {missing}"
