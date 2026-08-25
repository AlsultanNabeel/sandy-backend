"""Do it now, instead of asking whether to do it.

Sandy used to answer «خلصت المهمة» with «متأكد بدك أعلّم المهمة كمكتملة؟» and
wait for a second sentence. The owner's objection, and it is the right one: he
already said it. A confirmation earns its cost when the action is hard to undo
and the machine might have misheard — and marking a task done is neither. It is
one word to reverse, he does it ten times a day, and the question doubled the
round trips for a result a second sentence could have undone anyway.

So the handlers that used to store a pending and ask now run the same executor
immediately, through the same code path the confirmation used to reach. Nothing
about *what happens* changed; the question in the middle is gone.

**What still asks, and why.** Deleting more than one thing at once — «احذف كل
المهام», «احذف المهام المكتملة» — is the one shape where a misheard sentence
costs work that cannot be spoken back into existence. That is a rule about
scale, not about danger: deleting one named task is direct, because the name is
the evidence that she heard it right.

`agent/guards.py` is the other confirmation layer and is unrelated — it guards
the tool dispatcher against a model that picks a destructive tool on its own.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


def run_now(
    action: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
    fallback_reply: str = "",
) -> Dict[str, Any]:
    """Execute a task action immediately, with no confirmation turn.

    `action` is the same dict the pending flow used to store, so the executors
    receive exactly what they always received — that is deliberate. Changing
    where a call comes from is a smaller change than changing what it is handed,
    and the executors are where the real work and the real replies live.
    """
    from app.agent.executor.pending.task_pending import (
        _exec_task_append_note,
        _exec_task_complete,
        _exec_task_complete_multi,
        _exec_task_delete_one,
        _exec_task_rename,
        _exec_task_replace_note,
        _exec_task_uncomplete,
        _exec_task_uncomplete_multi,
        _exec_task_update_due_date,
        _exec_task_update_due_time,
    )

    table: Dict[str, Callable[..., Dict[str, Any]]] = {
        "complete": _exec_task_complete,
        "complete_multi": _exec_task_complete_multi,
        "uncomplete": _exec_task_uncomplete,
        "uncomplete_multi": _exec_task_uncomplete_multi,
        "rename": _exec_task_rename,
        "append_note": _exec_task_append_note,
        "replace_note": _exec_task_replace_note,
        "update_due_date": _exec_task_update_due_date,
        "update_due_time": _exec_task_update_due_time,
        "delete_one": _exec_task_delete_one,
    }

    name = str(action.get("action", ""))
    fn = table.get(name)
    if fn is None:
        # Not a mapped action: this must not silently do nothing, because the
        # caller has already told the user it is happening.
        logger.warning("[task] run_now has no executor for %r", name)
        return {"handled": True, "ok": False,
                "reply": fallback_reply or "ما قدرت أنفّذ الطلب."}

    return fn(
        action,
        session=session,
        session_file=session_file,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        save_session_fn=save_session_fn,
    )
