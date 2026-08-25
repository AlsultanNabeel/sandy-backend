"""Task notes handlers."""
from typing import Any, Dict


from app.agent.pending import create_pending_action

from app.features.tasks_store import (
    resolve_task_reference_for_write,
)
from app.agent.executor.helpers import _has_visible_task_note


from app.agent.executor.task_handlers._common import (
    _format_task_choices,
)
from app.agent.executor.task_handlers._now import run_now


def _handle_rename(
    task_reference: str,
    task_text: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
    result = resolve_task_reference_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("task_aliases", {}),
    )
    status = result.get("status")
    task_obj = result.get("task")
    new_text = task_text.strip()

    if status in {"empty", "missing", "not_found"}:
        reply = "ما لقيت هاي المهمة ضمن المهام النشطة. اعرض المهام مرة ثانية واختر مهمة موجودة."
        ok = False
    elif status == "ambiguous":
        choices = [
            {"id": task.get("id", ""), "text": task.get("text", "")}
            for task in result.get("matches", [])[:5]
            if task.get("id")
        ]
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "clarify_task_choice",
                "target_action": "rename",
                "choices": choices,
                "new_text": new_text,
                "confirmation_status": "clarification",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = (
            "لقيت أكثر من مهمة مطابقة:\n"
            + _format_task_choices(choices)
            + "\nاختار واحدة: الأولى، الثانية، أو رقم المهمة."
        )
    elif not new_text:
        reply = "شو الاسم الجديد للمهمة؟"
    elif task_obj:
        return run_now(
            {"type": "task", "action": "rename",
             "task_id": task_obj.get("id", ""),
             "old_text": task_obj.get("text", ""), "new_text": new_text},
            session=session, session_file=session_file, mongo_db=mongo_db,
            tasks_file=tasks_file, save_session_fn=save_session_fn)
    else:
        reply = "ما قدرت أحدد المهمة."
        ok = False
    return {"handled": True, "ok": ok, "reply": reply}




def _handle_append_note(
    task_reference: str,
    task_text: str,
    task_notes: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
    result = resolve_task_reference_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("task_aliases", {}),
    )
    status = result.get("status")
    task_obj = result.get("task")
    note_text = task_notes or task_text

    if status in {"empty", "missing", "not_found"}:
        reply = "ما لقيت هاي المهمة ضمن المهام النشطة. اعرض المهام مرة ثانية واختر مهمة موجودة."
        ok = False
    elif status == "ambiguous":
        choices = [
            {"id": task.get("id", ""), "text": task.get("text", "")}
            for task in result.get("matches", [])[:5]
            if task.get("id")
        ]
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "clarify_task_choice",
                "target_action": "append_note",
                "choices": choices,
                "note": note_text,
                "confirmation_status": "clarification",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = (
            "لقيت أكثر من مهمة مطابقة:\n"
            + _format_task_choices(choices)
            + "\nاختار واحدة: الأولى، الثانية، أو رقم المهمة."
        )
    elif not note_text:
        reply = "شو الملاحظة اللي بدك أضيفها؟"
    elif task_obj:
        return run_now(
            {"type": "task", "action": "append_note",
             "task_id": task_obj.get("id", ""),
             "text": task_obj.get("text", ""), "note": note_text},
            session=session, session_file=session_file, mongo_db=mongo_db,
            tasks_file=tasks_file, save_session_fn=save_session_fn)
    else:
        reply = "ما قدرت أحدد المهمة."
        ok = False
    return {"handled": True, "ok": ok, "reply": reply}




def _handle_replace_note(
    task_reference: str,
    task_text: str,
    task_notes: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
    result = resolve_task_reference_for_write(
        task_reference,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        aliases=session.get("task_aliases", {}),
    )
    status = result.get("status")
    task_obj = result.get("task")
    note_text = task_notes or task_text

    if status in {"empty", "missing", "not_found"}:
        reply = "ما لقيت هاي المهمة ضمن المهام النشطة. اعرض المهام مرة ثانية واختر مهمة موجودة."
        ok = False
    elif status == "ambiguous":
        choices = [
            {
                "id": task.get("id", ""),
                "text": task.get("text", ""),
                "notes": task.get("notes", ""),
            }
            for task in result.get("matches", [])[:5]
            if task.get("id")
        ]
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "clarify_task_choice",
                "target_action": "replace_note",
                "choices": choices,
                "note": note_text,
                "confirmation_status": "clarification",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        reply = (
            "لقيت أكثر من مهمة مطابقة:\n"
            + _format_task_choices(choices)
            + "\nاختار واحدة: الأولى، الثانية، أو رقم المهمة."
        )
    elif not note_text:
        reply = "شو الملاحظة الجديدة؟"
    elif task_obj:
        # «استبدل» على مهمة بلا ملاحظة معناه «ضيف». كان بيسأل عن الفرق قبل ما
        # ينفّذ؛ هلّق بينفّذ وبيقول شو صار — الفرق بيبان بالردّ، مش بسؤال قبله.
        return run_now(
            {"type": "task",
             "action": ("replace_note" if _has_visible_task_note(task_obj)
                        else "append_note"),
             "task_id": task_obj.get("id", ""),
             "text": task_obj.get("text", ""), "note": note_text},
            session=session, session_file=session_file, mongo_db=mongo_db,
            tasks_file=tasks_file, save_session_fn=save_session_fn)
    else:
        reply = "ما قدرت أحدد المهمة."
        ok = False
    return {"handled": True, "ok": ok, "reply": reply}
