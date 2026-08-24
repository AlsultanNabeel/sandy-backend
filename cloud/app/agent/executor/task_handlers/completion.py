"""Task completion handlers."""
from typing import Any, Dict


from app.agent.pending import create_pending_action

from app.features.tasks_store import (
    resolve_completed_task_reference_for_write,
    resolve_completed_task_references_for_write,
    resolve_task_references_for_write,
    complete_all_tasks,
)


from app.agent.executor.task_handlers._common import (
    _ambiguous_choice_reply,
    _format_task_choices,
)


def _handle_uncomplete_multi(
    task_reference: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
    result = resolve_completed_task_references_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("completed_task_aliases", {}),
    )
    status = result.get("status")
    tasks = result.get("tasks", [])

    if status in {"empty", "missing", "not_found"}:
        reply = "ما لقيت هاي المهام ضمن المهام المكتملة. اعرض المهام المكتملة مرة ثانية واختر مهام موجودة."
        ok = False
    elif status == "ambiguous":
        reply = (
            "لقيت أكثر من مهمة مكتملة مطابقة:\n"
            + _format_task_choices(result.get("matches", [])[:5])
            + "\nاكتبها بشكل أوضح."
        )
    elif status == "single":
        reply = (
            "لقيت مهمة واحدة فقط. لإلغاء اكتمال مهمة واحدة استخدم: رجّعي المهمة الأولى."
        )
    elif status in {"matched", "partial"} and tasks:
        missing_refs = result.get("missing_references", [])
        task_items = [
            {"id": task.get("id", ""), "text": task.get("text", "")}
            for task in tasks
            if task.get("id")
        ]
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "uncomplete_multi",
                "items": task_items,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        lines = "\n".join(f"- {item['text']}" for item in task_items)
        if status == "partial":
            missing_text = "، ".join(str(ref) for ref in missing_refs)
            reply = (
                f"بعض المهام غير موجودة ضمن المكتملة: {missing_text}\n\n"
                f"لقيت هاي المهام فقط:\n{lines}\n\n"
                f"متأكد بدك أرجّعها لقائمة المهام النشطة؟"
            )
        else:
            reply = f"متأكد بدك أرجّع هاي المهام لقائمة المهام النشطة؟\n{lines}"
    else:
        reply = "ما قدرت أحدد المهام المكتملة."
        ok = False
    return {"handled": True, "ok": ok, "reply": reply}




def _handle_uncomplete(
    task_reference: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
    result = resolve_completed_task_reference_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("completed_task_aliases", {}),
    )
    status = result.get("status")
    task_obj = result.get("task")

    if status in {"empty", "missing", "not_found"}:
        reply = "ما لقيت هاي المهمة ضمن المهام المكتملة. اعرض المهام المكتملة مرة ثانية واختر مهمة موجودة."
        ok = False
    elif status == "ambiguous":
        reply = (
            "لقيت أكثر من مهمة مكتملة مطابقة:\n"
            + _format_task_choices(result.get("matches", [])[:5])
            + "\nاكتب اسم المهمة بشكل أوضح."
        )
    elif task_obj:
        task_id = task_obj.get("id", "")
        task_text = task_obj.get("text", "")
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "uncomplete",
                "task_id": task_id,
                "text": task_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = f"متأكد بدك أرجّع المهمة لقائمة المهام النشطة؟\n- {task_text}"
    else:
        reply = "ما قدرت أحدد المهمة المكتملة."
        ok = False
    return {"handled": True, "ok": ok, "reply": reply}




def _handle_complete(
    task_reference: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
    result = resolve_task_references_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("task_aliases", {}),
    )
    status = result.get("status")
    tasks = result.get("tasks", [])

    if status in {"empty", "missing", "not_found"}:
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "clarify_task_write",
                "target_action": "complete_multi",
                "missing": "reference",
                "reference": "",
                "value_key": "",
                "value": "",
                "repeat_reply": "أي مهمة بدك أعلّمها كمكتملة؟ احكي اسمها أو اطلب قائمة المهام.",
                "confirmation_status": "clarification",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = "أي مهمة بدك أعلّمها كمكتملة؟ احكي اسمها أو اطلب قائمة المهام."
    elif status == "ambiguous":
        reply = _ambiguous_choice_reply(
            result,
            target_action="complete_one",
            session=session,
            session_file=session_file,
            mongo_db=mongo_db,
            save_session_fn=save_session_fn,
        )
    elif status == "single":
        task = tasks[0] if tasks else {}
        task_id = str(task.get("id", "")).strip()
        task_text = str(task.get("text", "")).strip()
        if not task_id:
            reply = "حددت المهمة، بس ما قدرت أجيب معرفها."
            ok = False
        else:
            session["pending_action"] = create_pending_action(
                {
                    "type": "task",
                    "action": "complete",
                    "task_id": task_id,
                    "text": task_text,
                    "confirmation_status": "pending",
                }
            )
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            reply = f"متأكد بدك أعلّم المهمة كمكتملة؟\n- {task_text}"
    else:
        reply = "ما قدرت أحدد المهمة."
        ok = False
    return {"handled": True, "ok": ok, "reply": reply}




def _handle_complete_multi(
    task_reference: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
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
            reply = f"المهمة ({bad_ref}) غير موجودة حالياً في قائمة المهام النشطة. اعرض المهام مرة ثانية واختر مهمة موجودة."
            ok = False
        else:
            reply = "أي مهمة بدك أعلّمها كمكتملة؟"
    elif status == "single":
        task = tasks[0] if tasks else {}
        task_text = str(task.get("text", "")).strip()
        if task.get("id"):
            session["pending_action"] = create_pending_action(
                {
                    "type": "task",
                    "action": "complete",
                    "task_id": task.get("id", ""),
                    "text": task_text,
                    "confirmation_status": "pending",
                }
            )
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            reply = f"لقيت مهمة واحدة فقط:\n- {task_text}\nبدك أعلّمها كمكتملة؟"
        else:
            reply = "حددت مهمة واحدة فقط، بس ما قدرت أجيب معرف المهمة."
            ok = False
    elif status == "ambiguous":
        reply = _ambiguous_choice_reply(
            result,
            target_action="complete_one",
            session=session,
            session_file=session_file,
            mongo_db=mongo_db,
            save_session_fn=save_session_fn,
        )
    elif status == "partial":
        missing_refs = result.get("missing_references", [])
        missing_text = "، ".join(str(ref) for ref in missing_refs)
        pending_tasks = [
            {"id": task.get("id", ""), "text": task.get("text", "")}
            for task in tasks
            if task.get("id")
        ]
        if pending_tasks:
            session["pending_action"] = create_pending_action(
                {
                    "type": "task",
                    "action": "complete_multi",
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
                f"بدك أعلّم الموجود منها كمكتمل؟"
            )
        else:
            reply = f"المهام التالية غير موجودة حالياً: {missing_text}"
            ok = False
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
                "action": "complete_multi",
                "tasks": pending_tasks,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = f"متأكد بدك أعلّم المهام التالية كمكتملة؟\n{lines}"
    else:
        reply = "ما قدرت أحدد المهام."
        ok = False
    return {"handled": True, "ok": ok, "reply": reply}




def _handle_complete_all(*, mongo_db, tasks_file):
    try:
        count = complete_all_tasks(mongo_db=mongo_db, tasks_file=tasks_file)
        if count == 0:
            return {"handled": True, "ok": False, "reply": "ما في مهام نشطة لإكمالها."}
        return {"handled": True, "reply": f"✅ كمّلت {count} مهمة."}
    except Exception as e:
        return {"handled": True, "ok": False, "error": f"complete_all: {type(e).__name__}",
                "reply": f"ما قدرت أكمّل المهام: {e}"}


# Common Arabic command prefixes the planner may leave on a task reference
# ("كمل مهمة ...", "احذف المهمة ..."). The planner should normally supply a clean
# `reference`; this strip-list is only a fallback and may drift, so keep it here.
