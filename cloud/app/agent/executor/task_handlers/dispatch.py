"""Task-action dispatcher: routes a parsed task action to its handler."""
from typing import Any, Dict



from app.utils.user_profiles import active_profile_is_guest


from app.agent.executor.task_handlers.listing import (
    _handle_list,
    _handle_list_overdue,
)
from app.agent.executor.task_handlers.creation import (
    _handle_create,
)
from app.agent.executor.task_handlers.completion import (
    _handle_uncomplete_multi,
    _handle_uncomplete,
    _handle_complete,
    _handle_complete_multi,
    _handle_complete_all,
)
from app.agent.executor.task_handlers.deletion import (
    _handle_delete,
    _handle_delete_multi,
    _handle_delete_all,
    _handle_delete_completed,
)
from app.agent.executor.task_handlers.due_date import (
    _handle_update_due_date,
    _handle_update_due_time,
    _handle_bulk_update_due_date,
)
from app.agent.executor.task_handlers.notes import (
    _handle_rename,
    _handle_append_note,
    _handle_replace_note,
)


_TASK_REFERENCE_PREFIXES = (
    "كمل مهمة",
    "كمل مهمه",
    "كمل المهمة",
    "كمل المهمه",
    "كمّل مهمة",
    "كمّل مهمه",
    "كمّل المهمة",
    "كمّل المهمه",
    "اكمل مهمة",
    "اكمل مهمه",
    "اكمل المهمة",
    "اكمل المهمه",
    "أنجز مهمة",
    "أنجز مهمه",
    "أنجز المهمة",
    "أنجز المهمه",
    "انجز مهمة",
    "انجز مهمه",
    "انجز المهمة",
    "انجز المهمه",
    "خلص مهمة",
    "خلص مهمه",
    "خلص المهمة",
    "خلص المهمه",
    "خلصت مهمة",
    "خلصت مهمه",
    "خلصت المهمة",
    "خلصت المهمه",
    "خصلت مهمة",
    "خصلت مهمه",
    "خصلت المهمة",
    "خصلت المهمه",
    "أنهيت مهمة",
    "أنهيت مهمه",
    "أنهيت المهمة",
    "أنهيت المهمه",
    "انهيت مهمة",
    "انهيت مهمه",
    "انهيت المهمة",
    "انهيت المهمه",
    "رجع مهمة",
    "رجع مهمه",
    "رجع المهمة",
    "رجع المهمه",
    "رجعي مهمة",
    "رجعي مهمه",
    "رجعي المهمة",
    "رجعي المهمه",
    "رجّع مهمة",
    "رجّع مهمه",
    "رجّع المهمة",
    "رجّع المهمه",
    "رجّعي مهمة",
    "رجّعي مهمه",
    "رجّعي المهمة",
    "رجّعي المهمه",
    "ارجع مهمة",
    "ارجع مهمه",
    "ارجع المهمة",
    "ارجع المهمه",
    "ارجعي مهمة",
    "ارجعي مهمه",
    "ارجعي المهمة",
    "ارجعي المهمه",
    "الغ إكمال مهمة",
    "الغ إكمال مهمه",
    "الغ إكمال المهمة",
    "الغ إكمال المهمه",
    "الغ اكمال مهمة",
    "الغ اكمال مهمه",
    "الغ اكمال المهمة",
    "الغ اكمال المهمه",
    "الغي إكمال مهمة",
    "الغي إكمال مهمه",
    "الغي إكمال المهمة",
    "الغي إكمال المهمه",
    "الغي اكمال مهمة",
    "الغي اكمال مهمه",
    "الغي اكمال المهمة",
    "الغي اكمال المهمه",
    "احذف مهمة",
    "احذف مهمه",
    "احذف المهمة",
    "احذف المهمه",
    "احذفي مهمة",
    "احذفي مهمه",
    "احذفي المهمة",
    "احذفي المهمه",
    "امسح مهمة",
    "امسح مهمه",
    "امسح المهمة",
    "امسح المهمه",
    "امسحي مهمة",
    "امسحي مهمه",
    "امسحي المهمة",
    "امسحي المهمه",
    "شيل مهمة",
    "شيل مهمه",
    "شيل المهمة",
    "شيل المهمه",
    "شيلي مهمة",
    "شيلي مهمه",
    "شيلي المهمة",
    "شيلي المهمه",
)


def handle_task_action(
    params: Dict[str, Any],
    *,
    user_message: str,
    normalized_user_message: str,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    create_chat_completion_fn,
    save_session_fn,
) -> Dict[str, Any]:
    if active_profile_is_guest():
        return {"handled": True, "ok": False, "reply": "سجّل دخولك عشان أقدر أنظّم مهامك 😊"}

    task_action = str(params.get("action", "create")).strip().lower()
    if task_action not in {
        "create",
        "list",
        "list_completed",
        "list_all",
        "list_overdue",
        "complete",
        "complete_multi",
        "complete_all",
        "uncomplete",
        "uncomplete_multi",
        "rename",
        "append_note",
        "replace_note",
        "clear_note",
        "update_due_date",
        "update_due_time",
        "delete",
        "delete_multi",
        "delete_all",
        "delete_completed",
        "bulk_update_due_date",
    }:
        return {"handled": True, "ok": False, "reply": "نوع إجراء المهمة غير صالح."}

    task_text = str(params.get("text", "")).strip()
    task_reference = str(params.get("reference", "")).strip()

    if (
        task_action
        in {
            "complete",
            "complete_multi",
            "uncomplete",
            "uncomplete_multi",
            "delete",
            "delete_multi",
        }
        and not task_reference
    ):
        task_reference = normalized_user_message

        for prefix in _TASK_REFERENCE_PREFIXES:
            if task_reference.startswith(prefix):
                task_reference = task_reference[len(prefix) :].strip(" .،")
                break

    task_due_iso = str(params.get("due_iso", "")).strip()
    task_due_text = str(params.get("due_text", "")).strip()
    task_time_text = str(
        params.get("time_text", "") or params.get("due_text", "")
    ).strip()
    task_notes = str(params.get("notes", "")).strip()

    _common = dict(
        session=session,
        session_file=session_file,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        save_session_fn=save_session_fn,
    )
    _with_ai = dict(**_common, create_chat_completion_fn=create_chat_completion_fn)

    _tasks_only = dict(mongo_db=mongo_db, tasks_file=tasks_file)

    if task_action in {"list", "list_completed", "list_all", "list_overdue"}:
        if task_action == "list_overdue":
            return _handle_list_overdue(**_tasks_only)
        return _handle_list(task_action, **_common)
    elif task_action == "rename":
        return _handle_rename(task_reference, task_text, **_common)
    elif task_action == "update_due_date":
        return _handle_update_due_date(
            task_reference, task_due_iso, task_due_text, **_with_ai
        )
    elif task_action == "append_note":
        return _handle_append_note(task_reference, task_text, task_notes, **_common)
    elif task_action in {"replace_note", "clear_note"}:
        note_content = "" if task_action == "clear_note" else task_notes
        return _handle_replace_note(task_reference, task_text, note_content, **_common)
    elif task_action == "update_due_time":
        return _handle_update_due_time(
            task_reference, task_due_iso, task_due_text, task_time_text, **_with_ai
        )
    elif task_action == "uncomplete_multi":
        return _handle_uncomplete_multi(task_reference, **_common)
    elif task_action == "uncomplete":
        return _handle_uncomplete(task_reference, **_common)
    elif task_action == "complete":
        return _handle_complete(task_reference, **_common)
    elif task_action == "complete_multi":
        return _handle_complete_multi(task_reference, **_common)
    elif task_action == "complete_all":
        return _handle_complete_all(**_tasks_only)
    elif task_action == "delete":
        return _handle_delete(task_reference, **_common)
    elif task_action == "delete_multi":
        return _handle_delete_multi(task_reference, **_common)
    elif task_action == "delete_all":
        return _handle_delete_all(
            session=session,
            session_file=session_file,
            mongo_db=mongo_db,
            save_session_fn=save_session_fn,
        )
    elif task_action == "delete_completed":
        return _handle_delete_completed(**_tasks_only)
    elif task_action == "bulk_update_due_date":
        return _handle_bulk_update_due_date(params, **_with_ai)
    else:  # create
        return _handle_create(
            task_text,
            task_due_iso,
            task_due_text,
            task_notes,
            task_priority=str(params.get("priority", "") or ""),
            task_project=str(params.get("project", "") or ""),
            **_with_ai,
        )
