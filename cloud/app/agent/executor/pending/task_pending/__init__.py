"""Task pending handlers + executors, split from an 853-line module.

Public surface unchanged: import any handler/executor from
app.agent.executor.pending.task_pending as before.
"""
from app.agent.executor.pending.task_pending.handlers import (
    _handle_clarify_task_choice,
    _handle_clarify_task_write,
    _handle_confirm_task_due_date,
)
from app.agent.executor.pending.task_pending.executors import (
    _exec_task_complete,
    _exec_task_complete_multi,
    _exec_task_uncomplete,
    _exec_task_rename,
    _exec_task_update_due_date,
    _exec_task_update_due_time,
    _exec_task_append_note,
    _exec_task_replace_note,
    _exec_task_uncomplete_multi,
    _exec_task_delete_one,
    _exec_task_delete_multi,
    _exec_task_delete_all,
    _exec_task_bulk_update_due_date,
)

__all__ = [
    "_handle_clarify_task_choice",
    "_handle_clarify_task_write",
    "_handle_confirm_task_due_date",
    "_exec_task_complete",
    "_exec_task_complete_multi",
    "_exec_task_uncomplete",
    "_exec_task_rename",
    "_exec_task_update_due_date",
    "_exec_task_update_due_time",
    "_exec_task_append_note",
    "_exec_task_replace_note",
    "_exec_task_uncomplete_multi",
    "_exec_task_delete_one",
    "_exec_task_delete_multi",
    "_exec_task_delete_all",
    "_exec_task_bulk_update_due_date",
]
