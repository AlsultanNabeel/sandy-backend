"""Bulk task operations: confirmation and reminder cleanup; fetch_url ranges."""
from unittest.mock import MagicMock, patch


def test_delete_completed_asks_first():
    from app.agent.executor.task_handlers.deletion import _handle_delete_completed
    session = {}
    with patch("app.features.tasks_store.delete_completed_tasks") as dele:
        out = _handle_delete_completed(session=session, session_file=None,
                                       mongo_db=None, save_session_fn=MagicMock())
    dele.assert_not_called()
    assert session["pending_action"]["action"] == "delete_completed"
    assert "متأكد" in out["reply"]


def test_complete_all_clears_the_tasks_reminders():
    from app.agent.executor.task_handlers import completion as c
    with patch.object(c, "active_task_ids", return_value=["t1", "t2"]), \
         patch.object(c, "complete_all_tasks", return_value=2), \
         patch.object(c, "delete_sandy_reminder_by_task_id") as drop:
        out = c._handle_complete_all(mongo_db=None, tasks_file=None)
    assert [call.args[0] for call in drop.call_args_list] == ["t1", "t2"]
    assert out.get("ok", True)


def test_fetch_url_refuses_carrier_grade_nat():
    from app.agent.tools.schemas import mcp_tools
    fake = [(None, None, None, None, ("100.64.0.1", 80))]
    with patch.object(mcp_tools.socket, "getaddrinfo", return_value=fake):
        assert mcp_tools._is_safe_public_url("http://example.test/") is False
    fake = [(None, None, None, None, ("93.184.216.34", 80))]
    with patch.object(mcp_tools.socket, "getaddrinfo", return_value=fake):
        assert mcp_tools._is_safe_public_url("http://example.test/") is True


def test_clear_note_writes_an_empty_note():
    from app.agent.executor.task_handlers import notes
    resolved = {"status": "single", "task": {"id": "t1", "text": "مهمة", "notes": "قديم"}}
    with patch.object(notes, "resolve_task_reference_for_write", return_value=resolved), \
         patch("app.agent.executor.pending.task_pending.executors.deps") as deps:
        deps.replace_task_note.return_value = True
        notes._handle_replace_note("مهمة", "مهمة", "", clear=True, session={},
                                   session_file=None, mongo_db=None, tasks_file=None,
                                   save_session_fn=MagicMock())
    assert deps.replace_task_note.call_args.args[:2] == ("t1", "")
