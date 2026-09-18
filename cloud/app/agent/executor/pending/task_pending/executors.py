"""Task pending executors: apply a confirmed task action."""
from typing import Any, Dict

import app.agent.executor.deps as deps

from app.agent.pending import clear_pending_action


def _exec_task_complete(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    task_text = str(pending.get("text", "")).strip()
    ok = deps.complete_task(task_id, mongo_db=mongo_db, tasks_file=tasks_file)
    if ok:
        deps.delete_sandy_reminder_by_task_id(task_id)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if ok:
        return {"handled": True, "reply": f"تمام، علّمت المهمة كمكتملة:\n- {task_text}"}
    return {"handled": True, "ok": False, "reply": "ما قدرت أكمل المهمة."}


def _exec_task_complete_multi(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    pending_tasks = pending.get("tasks", [])
    completed_names = []
    failed_names = []
    for task in pending_tasks:
        task_id = str(task.get("id", "")).strip()
        task_text = str(task.get("text", "")).strip()
        ok = deps.complete_task(task_id, mongo_db=mongo_db, tasks_file=tasks_file)
        if ok:
            deps.delete_sandy_reminder_by_task_id(task_id)
            completed_names.append(task_text)
        else:
            failed_names.append(task_text)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if completed_names and not failed_names:
        lines = "\n".join(f"- {name}" for name in completed_names)
        return {
            "handled": True,
            "reply": f"تمام، علّمت {len(completed_names)} مهام كمكتملة:\n{lines}",
        }
    if completed_names:
        ok_lines = "\n".join(f"- {name}" for name in completed_names)
        fail_lines = "\n".join(f"- {name}" for name in failed_names)
        return {
            "handled": True,
            "reply": f"علّمت كمكتملة:\n{ok_lines}\nوما قدرت أكمل:\n{fail_lines}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أكمل المهام المحددة."}


def _exec_task_uncomplete(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    task_text = str(pending.get("text", "")).strip()
    ok = deps.uncomplete_task(task_id, mongo_db=mongo_db, tasks_file=tasks_file)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if ok:
        return {
            "handled": True,
            "reply": f"تمام، رجّعت المهمة لقائمة المهام النشطة: {task_text}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أرجّع المهمة."}


def _exec_task_rename(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    old_text = str(pending.get("old_text", "")).strip()
    new_text = str(pending.get("new_text", "")).strip()
    ok = deps.rename_task(task_id, new_text, mongo_db=mongo_db, tasks_file=tasks_file)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if ok:
        return {
            "handled": True,
            "reply": f"تمام، عدّلت اسم المهمة:\nمن: {old_text}\nإلى: {new_text}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أعدل اسم المهمة."}


def _move_task_reminder(task_id: str, task_text: str, due_iso: str) -> bool:
    """Point the task's linked reminder at its new time. True on success.

    The store deletes by ``linked_task_id``, so the old reminder goes first and
    the new one is written after; a failure leaves the task without one, which
    the caller reports rather than calling it done.
    """
    deps.delete_sandy_reminder_by_task_id(task_id)
    result = deps.add_reminder(text=task_text, remind_at_iso=due_iso, linked_task_id=task_id)
    return bool(result.get("success"))


def _exec_task_update_due_date(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    task_text = str(pending.get("text", "")).strip()
    due_iso = str(pending.get("due_iso", "")).strip()
    new_due_text = str(pending.get("new_due_text", "")).strip()
    result = deps.update_task_due_date(
        task_id, due_iso, mongo_db=mongo_db, tasks_file=tasks_file
    )
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if result.get("ok"):
        if result.get("due_at") and not _move_task_reminder(task_id, task_text, result["due_at"]):
            return {
                "handled": True, "ok": False, "error": "reminder_not_moved",
                "reply": f"عدّلت تاريخ المهمة، بس صار خطأ وأنا بحدّث التذكير تبعها:\n- {task_text}",
            }
        return {
            "handled": True,
            "reply": f"تمام، عدّلت تاريخ المهمة:\n- {task_text}\nالتاريخ الجديد: {new_due_text}",
        }
    reason = result.get("reason")
    if reason == "past":
        return {
            "handled": True, "ok": False,
            "reply": "التاريخ الجديد بالماضي. أعطني تاريخ اليوم أو تاريخ لاحق.",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أعدل تاريخ المهمة."}


def _exec_task_update_due_time(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    task_text = str(pending.get("text", "")).strip()
    due_iso = str(pending.get("due_iso", "")).strip()
    new_due_text = str(pending.get("new_due_text", "")).strip()
    result = deps.update_task_due_time(
        task_id, due_iso, mongo_db=mongo_db, tasks_file=tasks_file
    )
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if not result.get("ok"):
        if result.get("reason") == "past":
            return {"handled": True, "ok": False, "reply": "الوقت الجديد بالماضي. أعطني وقت لاحق."}
        return {"handled": True, "ok": False, "reply": "ما قدرت أعدل وقت المهمة."}
    if _move_task_reminder(task_id, task_text, due_iso):
        return {
            "handled": True,
            "reply": f"تمام، عدّلت وقت تذكير المهمة:\n- {task_text}\nالوقت الجديد: {new_due_text}",
        }
    # The task moved but nothing will remind the user: not a success.
    return {
        "handled": True, "ok": False, "error": "reminder_not_moved",
        "reply": f"عدّلت وقت المهمة، بس صار خطأ وأنا بحدّث التذكير تبعها:\n- {task_text}",
    }


def _exec_task_append_note(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    task_text = str(pending.get("text", "")).strip()
    note_text = str(pending.get("note", "")).strip()
    ok = deps.append_task_note(
        task_id, note_text, mongo_db=mongo_db, tasks_file=tasks_file
    )
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if ok:
        return {
            "handled": True,
            "reply": f"تمام، أضفت الملاحظة على المهمة:\n- {task_text}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أضيف الملاحظة للمهمة."}


def _exec_task_replace_note(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    task_text = str(pending.get("text", "")).strip()
    note_text = str(pending.get("note", "")).strip()
    ok = deps.replace_task_note(
        task_id, note_text, mongo_db=mongo_db, tasks_file=tasks_file
    )
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if ok:
        return {
            "handled": True,
            "reply": f"تمام، استبدلت ملاحظة المهمة:\n- {task_text}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أستبدل ملاحظة المهمة."}


def _exec_task_uncomplete_multi(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_items = pending.get("items", [])
    restored = []
    failed = []
    for item in task_items:
        task_id = str(item.get("id", "")).strip()
        task_text = str(item.get("text", "")).strip()
        if deps.uncomplete_task(task_id, mongo_db=mongo_db, tasks_file=tasks_file):
            restored.append(task_text)
        else:
            failed.append(task_text)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if restored and not failed:
        lines = "\n".join(f"- {text}" for text in restored)
        return {
            "handled": True,
            "reply": f"تمام، رجّعت هاي المهام لقائمة المهام النشطة:\n{lines}",
        }
    if restored and failed:
        ok_lines = "\n".join(f"- {text}" for text in restored)
        fail_lines = "\n".join(f"- {text}" for text in failed)
        return {
            "handled": True,
            "reply": f"رجّعت بعض المهام:\n{ok_lines}\n\nوما قدرت أرجّع:\n{fail_lines}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أرجّع المهام."}


def _exec_task_delete_one(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    task_id = str(pending.get("task_id", "")).strip()
    task_text = str(pending.get("text", "")).strip()
    ok = deps.delete_task(task_id, mongo_db=mongo_db, tasks_file=tasks_file)
    if ok:
        deps.delete_sandy_reminder_by_task_id(task_id)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if ok:
        return {"handled": True, "reply": f"تمام، حذفت المهمة: {task_text}"}
    return {"handled": True, "ok": False, "reply": "ما قدرت أحذف المهمة."}


def _exec_task_delete_multi(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    pending_tasks = pending.get("tasks", [])
    deleted_names = []
    failed_names = []
    for task in pending_tasks:
        task_id = str(task.get("id", "")).strip()
        task_text = str(task.get("text", "")).strip()
        ok = deps.delete_task(task_id, mongo_db=mongo_db, tasks_file=tasks_file)
        if ok:
            deps.delete_sandy_reminder_by_task_id(task_id)
            deleted_names.append(task_text)
        else:
            failed_names.append(task_text)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if deleted_names and not failed_names:
        lines = "\n".join(f"- {name}" for name in deleted_names)
        return {
            "handled": True,
            "reply": f"تمام، حذفت {len(deleted_names)} مهام:\n{lines}",
        }
    if deleted_names:
        ok_lines = "\n".join(f"- {name}" for name in deleted_names)
        fail_lines = "\n".join(f"- {name}" for name in failed_names)
        return {
            "handled": True,
            "reply": f"حذفت:\n{ok_lines}\nوما قدرت أحذف:\n{fail_lines}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أحذف المهام المحددة."}


def _exec_task_delete_all(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    deleted_count = deps.delete_active_tasks(mongo_db=mongo_db, tasks_file=tasks_file)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if deleted_count == 0:
        return {
            "handled": True, "ok": False,
            "reply": "ما في مهام نشطة للحذف. المهام المكتملة بقيت كما هي.",
        }
    return {
        "handled": True,
        "reply": f"تمام، حذفت كل المهام النشطة ({deleted_count}) وتركت المهام المكتملة.",
    }


def _exec_task_bulk_update_due_date(
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    tasks_to_update = pending.get("tasks", [])
    to_due_iso = pending.get("to_due_iso", "")
    to_due_text = pending.get("to_due_text", "")
    updated = []
    failed = []
    for task_item in tasks_to_update:
        task_id = str(task_item.get("id", "")).strip()
        task_text_item = str(task_item.get("text", "")).strip()
        if not task_id or not to_due_iso:
            failed.append(task_text_item)
            continue
        result = deps.update_task_due_date(
            task_id, to_due_iso, mongo_db=mongo_db, tasks_file=tasks_file
        )
        if result.get("ok"):
            if result.get("due_at"):
                _move_task_reminder(task_id, task_text_item, result["due_at"])
            updated.append(task_text_item)
        else:
            failed.append(task_text_item)
    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    if updated and not failed:
        lines = "\n".join(f"- {t}" for t in updated)
        return {
            "handled": True,
            "reply": f"✅ أجّلت {len(updated)} مهام إلى {to_due_text}:\n{lines}",
        }
    if updated and failed:
        ok_lines = "\n".join(f"- {t}" for t in updated)
        fail_lines = "\n".join(f"- {t}" for t in failed)
        return {
            "handled": True,
            "reply": f"أجّلت:\n{ok_lines}\n\nوما قدرت أؤجل:\n{fail_lines}",
        }
    return {"handled": True, "ok": False, "reply": "ما قدرت أؤجل المهام."}
