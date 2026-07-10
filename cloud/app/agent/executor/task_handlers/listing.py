"""Task listing handlers."""
from datetime import datetime
from typing import Any, Dict


from app.utils.time import USER_TZ

from app.features.tasks_store import (
    build_task_display,
    build_completed_task_display,
    build_all_tasks_display,
    load_overdue_tasks,
)




def _handle_list(
    task_action: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    if task_action == "list":
        reply, aliases = build_task_display(mongo_db=mongo_db, tasks_file=tasks_file)
        session["task_aliases"] = aliases
    elif task_action == "list_completed":
        reply, aliases = build_completed_task_display(
            mongo_db=mongo_db, tasks_file=tasks_file
        )
        session["completed_task_aliases"] = aliases
    else:  # list_all
        reply, active_aliases, completed_aliases = build_all_tasks_display(
            mongo_db=mongo_db, tasks_file=tasks_file
        )
        session["task_aliases"] = active_aliases
        session["completed_task_aliases"] = completed_aliases
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    return {"handled": True, "reply": reply}




def _handle_list_overdue(*, mongo_db, tasks_file):
    tasks = load_overdue_tasks(mongo_db=mongo_db, tasks_file=tasks_file)
    if not tasks:
        return {"handled": True, "reply": "ما في مهام متأخرة 🎉"}
    lines = []
    for i, t in enumerate(tasks[:20], 1):
        text = str(t.get("text") or t.get("title") or "").strip()
        due = str(t.get("due_iso") or t.get("due") or "").strip()
        try:
            due_disp = (
                datetime.fromisoformat(due.replace("Z", "+00:00"))
                .astimezone(USER_TZ)
                .strftime("%d/%m")
            )
        except Exception:
            due_disp = due[:10] if due else ""
        lines.append(f"{i}. {text}" + (f" (كان موعدها {due_disp})" if due_disp else ""))
    return {
        "handled": True,
        "reply": f"⏰ المهام المتأخرة ({len(tasks)}):\n" + "\n".join(lines),
    }
