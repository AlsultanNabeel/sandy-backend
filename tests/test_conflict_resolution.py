from datetime import datetime, timedelta
from unittest.mock import patch

from app.agent.conflict_resolution import check_conflicts
from app.agent.executor.task_handlers import handle_task_action
from app.utils.time import USER_TZ
from app.utils.user_profiles import set_active_user_profile


_OWNER_PROFILE = {"relation": "owner", "permissions": "all", "tone": "casual", "name": "Test"}


def _save_session(*args, **kwargs):
    return None


def _dt(days_from_now: int, hour: int = 10, minute: int = 0) -> datetime:
    base = datetime.now(USER_TZ) + timedelta(days=days_from_now)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def test_check_conflicts_detects_study_vs_meeting_same_day():
    day = _dt(days_from_now=2, hour=9)
    tasks = [
        {
            "id": "task_exam_1",
            "text": "امتحان الفيزياء",
            "due_at": day.isoformat(),
            "due": "",
            "notes": "",
        }
    ]
    result = check_conflicts(
        {
            "id": "t_new",
            "source": "task",
            "title": "اجتماع الفريق",
            "start_iso": day.replace(hour=15).isoformat(),
            "end_iso": day.replace(hour=16).isoformat(),
        },
        tasks=tasks,
    )

    assert result["has_conflict"] is True
    assert "ولقيت اجتماع الفريق نفس اليوم" in result["alert_text"]
    assert "اقتراحات من الأوقات الفاضية" in result["alert_text"]


def test_check_conflicts_returns_no_conflict_for_different_days():
    day_1 = _dt(days_from_now=2, hour=10)
    day_2 = _dt(days_from_now=4, hour=10)

    tasks = [{"id": "t1", "text": "امتحان", "due_at": day_1.isoformat(), "due": "", "notes": ""}]

    result = check_conflicts(
        {
            "id": "t_new",
            "source": "task",
            "title": "اجتماع",
            "start_iso": day_2.isoformat(),
            "end_iso": (day_2 + timedelta(hours=1)).isoformat(),
        },
        tasks=tasks,
    )

    assert result["has_conflict"] is False
    assert result["alert_text"] == ""


def test_check_conflicts_detects_overlapping_meetings_same_time():
    day = _dt(days_from_now=3, hour=14)
    tasks = [{"id": "t_old", "text": "اجتماع المنتج", "due_at": day.isoformat(), "due": "", "notes": ""}]

    result = check_conflicts(
        {
            "id": "t_new",
            "source": "task",
            "title": "اجتماع الفريق",
            "start_iso": day.isoformat(),
            "end_iso": (day + timedelta(hours=1)).isoformat(),
        },
        tasks=tasks,
    )

    assert result["has_conflict"] is True
    assert "اجتماع المنتج" in result["alert_text"]


@patch("app.agent.executor.task_handlers.creation.run_conflict_check_after_task_add")
@patch("app.agent.executor.task_handlers.creation.add_task")
def test_task_create_appends_conflict_alert(mock_add_task, mock_conflict):
    set_active_user_profile(_OWNER_PROFILE)
    mock_add_task.return_value = "task_new_1"
    mock_conflict.return_value = {
        "alert_text": "نبيل، عندك امتحان الخميس ولقيت موعد اجتماع نفس اليوم — بعدّل؟"}

    due = _dt(days_from_now=1, hour=11).isoformat()
    result = handle_task_action(
        {"action": "create", "text": "موعد اجتماع", "due_iso": due},
        user_message="ضيفي مهمة موعد اجتماع بكرا",
        normalized_user_message="ضيفي مهمة موعد اجتماع بكرا",
        session={},
        session_file=None,
        mongo_db=None,
        tasks_file=None,
        create_chat_completion_fn=None,
        save_session_fn=_save_session,
    )
    set_active_user_profile(None)

    assert result["handled"] is True
    assert "⚠️ نبيل" in result["reply"]
    mock_conflict.assert_called_once()
