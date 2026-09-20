"""Reminder tool behaviour the model relies on."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.utils.time import USER_TZ

from app.agent.executor import reminder_handlers as rh

_R = [
    {"id": "r1", "text": "دوا الضغط", "remind_at": "2099-01-01T09:00:00+02:00"},
    {"id": "r2", "text": "دوا السكر", "remind_at": "2099-01-01T21:00:00+02:00"},
]


def _run(params):
    return rh.handle_reminder_action(
        params, user_message="", normalized_user_message="", session={},
        session_file=None, mongo_db=None, tasks_file=None,
        create_chat_completion_fn=None, save_session_fn=MagicMock())


def test_delete_with_several_matches_asks_instead_of_deleting_all():
    with patch.object(rh, "load_reminders", return_value=_R), \
         patch.object(rh, "delete_reminder") as dele:
        out = _run({"action": "delete", "text": "دوا"})
    dele.assert_not_called()
    assert out["ok"] is False and "أكثر من تذكير" in out["reply"]


def test_delete_by_id_deletes_exactly_that_one():
    with patch.object(rh, "load_reminders", return_value=_R), \
         patch.object(rh, "delete_reminder", return_value=True) as dele:
        out = _run({"action": "delete", "reminder_id": "r2"})
    dele.assert_called_once_with("r2")
    assert out.get("ok", True)


def test_update_with_only_a_new_title_renames():
    with patch.object(rh, "load_reminders", return_value=_R), \
         patch.object(rh, "update_reminder", return_value={"success": True}) as upd:
        out = _run({"action": "update", "text": "دوا الضغط", "new_text": "حبة الضغط"})
    assert upd.call_args.kwargs["title"] == "حبة الضغط"
    assert "حبة الضغط" in out["reply"]


def test_failed_create_is_not_ok():
    with patch.object(rh, "add_reminder", return_value={"success": False}):
        soon = (datetime.now(USER_TZ) + timedelta(days=1)).isoformat()
        out = _run({"action": "create", "text": "اتصل", "remind_at_iso": soon})
    assert out["ok"] is False
