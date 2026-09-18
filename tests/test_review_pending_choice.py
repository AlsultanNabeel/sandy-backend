"""A numbered answer to "which task?" is a choice, not an unrelated message."""
from unittest.mock import MagicMock

from app.agent.executor.pending.dispatch import execute_pending_action
from app.agent.pending import create_pending_action


def _session():
    return {"pending_action": create_pending_action({
        "type": "task", "action": "clarify_task_choice", "target_action": "delete_one",
        "choices": [{"id": "a", "text": "مهمة أ"}, {"id": "b", "text": "مهمة ب"}],
        "confirmation_status": "clarification",
    })}


def _run(msg, session):
    return execute_pending_action(
        user_message=msg, session=session, session_file=None, mongo_db=None,
        tasks_file=None, save_session_fn=MagicMock())


def test_second_is_picked():
    out = _run("الثانية", _session())
    assert "مهمة ب" in out["reply"]


def test_digit_is_picked():
    out = _run("2", _session())
    assert "مهمة ب" in out["reply"]


def test_an_unrelated_message_moves_on():
    s = _session()
    out = _run("شو الطقس اليوم", s)
    assert out == {"handled": False}
    assert s["pending_action"] is None
