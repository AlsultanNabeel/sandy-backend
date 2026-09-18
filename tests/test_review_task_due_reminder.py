"""Moving a task's due time must move its linked reminder with it.

Regression: the executor called a removed calendar helper after deleting the
old reminder, so the reminder was lost and the turn crashed.
"""
import unittest
from unittest.mock import MagicMock, patch

from app.agent.executor.pending.task_pending.executors import _exec_task_update_due_time

_PENDING = {
    "task_id": "t1",
    "text": "اشتري خبز",
    "due_iso": "2026-09-20T09:00:00+03:00",
    "new_due_text": "بكرا الصبح",
}


def _run(add_result):
    deps = "app.agent.executor.pending.task_pending.executors.deps"
    with patch(deps) as d:
        d.update_task_due_time.return_value = {"ok": True}
        d.add_reminder.return_value = add_result
        out = _exec_task_update_due_time(
            dict(_PENDING),
            session={},
            session_file=None,
            mongo_db=None,
            tasks_file=None,
            save_session_fn=MagicMock(),
        )
        return out, d


class TestTaskDueReminder(unittest.TestCase):
    def test_reminder_recreated_at_new_time(self):
        out, d = _run({"success": True})
        d.delete_sandy_reminder_by_task_id.assert_called_once_with("t1")
        d.add_reminder.assert_called_once_with(
            text="اشتري خبز", remind_at_iso=_PENDING["due_iso"], linked_task_id="t1"
        )
        self.assertTrue(out["ok"])
        self.assertIn("بكرا الصبح", out["reply"])

    def test_reminder_failure_is_reported_honestly(self):
        out, _ = _run({"success": False})
        self.assertTrue(out["handled"])
        self.assertIn("خطأ", out["reply"])
        self.assertNotIn("Google", out["reply"])


if __name__ == "__main__":
    unittest.main()
