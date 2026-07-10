"""Task deletion handlers."""
from typing import Any, Dict


from app.agent.pending import create_pending_action

from app.features.tasks_store import (
    resolve_task_reference_for_write,
    resolve_task_references_for_write,
    delete_completed_tasks,
)


from app.agent.executor.task_handlers._common import (
    _ambiguous_choice_reply,
    _format_task_choices,
)


def _handle_delete(
    task_reference: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    result = resolve_task_reference_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("task_aliases", {}),
    )
    status = result.get("status")
    task_obj = result.get("task")

    if status in {"empty", "missing", "not_found"}:
        reply = "أي مهمة بدك أحذف بالضبط؟ اطلب قائمة المهام أو اكتب اسمها."
    elif status == "ambiguous":
        reply = _ambiguous_choice_reply(
            result,
            target_action="delete_one",
            session=session,
            session_file=session_file,
            mongo_db=mongo_db,
            save_session_fn=save_session_fn,
        )
    elif task_obj:
        task_id = task_obj.get("id", "")
        task_text = task_obj.get("text", "")
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "delete_one",
                "task_id": task_id,
                "text": task_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = f"متأكد بدك أحذف المهمة: {task_text}؟"
    else:
        reply = "ما قدرت أحدد المهمة."
    return {"handled": True, "reply": reply}




def _handle_delete_multi(
    task_reference: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    result = resolve_task_references_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("task_aliases", {}),
    )
    status = result.get("status")
    tasks = result.get("tasks", [])

    if status in {"empty", "missing", "not_found"}:
        bad_ref = str(result.get("reference", "")).strip()
        if bad_ref:
            reply = f"المهمة رقم/مرجع ({bad_ref}) غير موجودة حالياً في قائمة المهام النشطة. اعرض المهام مرة ثانية واختر مهمة موجودة."
        else:
            reply = "أي مهام بدك أحذف بالضبط؟"
    elif status == "partial":
        missing_refs = result.get("missing_references", [])
        missing_text = "، ".join(str(ref) for ref in missing_refs)
        pending_tasks = [
            {"id": task.get("id", ""), "text": task.get("text", "")}
            for task in tasks
            if task.get("id")
        ]
        if len(pending_tasks) == 1:
            task = pending_tasks[0]
            session["pending_action"] = create_pending_action(
                {
                    "type": "task",
                    "action": "delete_one",
                    "task_id": task.get("id", ""),
                    "text": task.get("text", ""),
                    "confirmation_status": "pending",
                }
            )
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            reply = (
                f"المهمة ({missing_text}) غير موجودة حالياً.\n"
                f"لقيت مهمة واحدة فقط:\n"
                f"- {task.get('text', '')}\n"
                f"بدك أحذفها؟"
            )
        elif len(pending_tasks) > 1:
            session["pending_action"] = create_pending_action(
                {
                    "type": "task",
                    "action": "delete_multi",
                    "tasks": pending_tasks,
                    "confirmation_status": "pending",
                }
            )
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            lines = "\n".join(f"- {task.get('text', '')}" for task in pending_tasks)
            reply = (
                f"المهام التالية غير موجودة: {missing_text}\n"
                f"لقيت المهام التالية فقط:\n"
                f"{lines}\n"
                f"بدك أحذف الموجود منها؟"
            )
        else:
            reply = f"المهام التالية غير موجودة حالياً: {missing_text}"
    elif status == "single":
        reply = "حددت مهمة واحدة فقط. إذا بدك حذف مهمة واحدة استخدم أمر حذف عادي، أو اذكر أكثر من مهمة."
    elif status == "ambiguous":
        reply = (
            "لقيت أكثر من مهمة مطابقة:\n"
            + _format_task_choices(result.get("matches", [])[:5])
            + "\nاكتب الأسماء بشكل أوضح."
        )
    elif tasks:
        pending_tasks = [
            {"id": task.get("id", ""), "text": task.get("text", "")}
            for task in tasks
            if task.get("id")
        ]
        lines = "\n".join(f"- {task.get('text', '')}" for task in pending_tasks)
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "delete_multi",
                "tasks": pending_tasks,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = f"متأكد بدك أحذف المهام التالية؟\n{lines}"
    else:
        reply = "ما قدرت أحدد المهام."
    return {"handled": True, "reply": reply}




def _handle_delete_all(
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    save_session_fn,
) -> Dict[str, Any]:
    session["pending_action"] = create_pending_action(
        {
            "type": "task",
            "action": "delete_all",
            "confirmation_status": "pending",
        }
    )
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    return {"handled": True, "reply": "متأكد بدك أحذف كل المهام؟"}




def _handle_delete_completed(*, mongo_db, tasks_file):
    try:
        count = delete_completed_tasks(mongo_db=mongo_db, tasks_file=tasks_file)
        if count == 0:
            return {"handled": True, "reply": "ما في مهام مكتملة لحذفها."}
        return {"handled": True, "reply": f"✅ حذفت {count} مهمة مكتملة."}
    except Exception as e:
        return {"handled": True, "reply": f"ما قدرت أحذف المهام المكتملة: {e}"}
