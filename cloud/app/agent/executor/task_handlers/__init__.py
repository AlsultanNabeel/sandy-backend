"""Task-action handlers, split by action group.

Public surface is unchanged: ``from app.agent.executor.task_handlers import
handle_task_action`` still works.
"""
from app.agent.executor.task_handlers.dispatch import handle_task_action

__all__ = ["handle_task_action"]
