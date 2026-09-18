"""Returning several completed tasks to active must actually restore them.

Regression: the handler passed the list under "tasks" while the executor read
"items", so every call restored nothing and said it could not.
"""
from unittest.mock import MagicMock, patch

from app.agent.executor.task_handlers.completion import _handle_uncomplete_multi


def test_uncomplete_multi_restores_each_task():
    resolved = {"status": "matched", "tasks": [
        {"id": "t1", "text": "أ"}, {"id": "t2", "text": "ب"}]}
    with patch("app.agent.executor.task_handlers.completion."
               "resolve_completed_task_references_for_write", return_value=resolved), \
         patch("app.agent.executor.pending.task_pending.executors.deps") as deps:
        deps.uncomplete_task.return_value = True
        out = _handle_uncomplete_multi(
            "1 و 2", session={}, session_file=None, mongo_db=None,
            tasks_file=None, save_session_fn=MagicMock())
    assert [c.args[0] for c in deps.uncomplete_task.call_args_list] == ["t1", "t2"]
    assert out.get("ok", True) is True
