"""Task pending-confirmation handlers (clarify choice/write, confirm due date)."""
from datetime import datetime
from typing import Any, Dict

import app.agent.executor.deps as deps

from app.utils.arabic_days import DATE_HINT_TOKENS
from app.utils.nlp_normalizer import normalize_user_message
from app.utils.time import USER_TZ
from app.agent.pending import create_pending_action, clear_pending_action
from app.agent.executor.helpers import (
    _has_visible_task_note,
    _is_quick_confirmation,
    _task_choice_index,
    _task_choice_pair_indexes,
    is_cancellation,
)


def _handle_clarify_task_choice(
    user_message: str,
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    save_session_fn,
    create_chat_completion_fn,
) -> Dict[str, Any]:
    if _is_quick_confirmation(user_message):
        return {
            "handled": True,
            "reply": "اختار رقم المهمة من القائمة، مثل: الأولى أو 1.",
        }

    choices = pending.get("choices", [])
    target_action = str(pending.get("target_action", "")).strip().lower()
    pair_indexes = _task_choice_pair_indexes(user_message, len(choices))

    if pair_indexes and target_action in {"complete_one", "delete_one"}:
        selected_tasks = [
            {"id": choices[i].get("id", ""), "text": choices[i].get("text", "")}
            for i in pair_indexes
            if choices[i].get("id")
        ]
        if len(selected_tasks) == 2:
            if target_action == "complete_one":
                session["pending_action"] = create_pending_action(
                    {
                        "type": "task",
                        "action": "complete_multi",
                        "tasks": selected_tasks,
                        "confirmation_status": "pending",
                    }
                )
                save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
                lines = "\n".join(
                    f"- {task.get('text', '')}" for task in selected_tasks
                )
                return {
                    "handled": True,
                    "reply": f"متأكد بدك أعلّم المهمتين كمكتملتين؟\n{lines}",
                }
            if target_action == "delete_one":
                session["pending_action"] = create_pending_action(
                    {
                        "type": "task",
                        "action": "delete_multi",
                        "tasks": selected_tasks,
                        "confirmation_status": "pending",
                    }
                )
                save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
                lines = "\n".join(
                    f"- {task.get('text', '')}" for task in selected_tasks
                )
                return {"handled": True, "reply": f"متأكد بدك تحذف المهمتين؟\n{lines}"}

    index = _task_choice_index(user_message)

    if index is None or index < 0 or index >= len(choices):
        lines = "\n".join(
            f"المهمة {i}: {task.get('text', '')}" for i, task in enumerate(choices, 1)
        )
        return {
            "handled": True,
            "reply": "ما فهمت اختيارك. اختار واحدة من هاي المهام:\n" + lines,
        }

    selected = choices[index]

    if target_action == "rename":
        task_id = str(selected.get("id", "")).strip()
        old_text = str(selected.get("text", "")).strip()
        new_text = str(pending.get("new_text", "")).strip()
        if not task_id or not new_text:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "ما قدرت أكمل تعديل الاسم. جرّب الأمر من جديد.",
            }
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "rename",
                "task_id": task_id,
                "old_text": old_text,
                "new_text": new_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        return {
            "handled": True,
            "reply": f"متأكد بدك تعدّل اسم المهمة؟\nمن: {old_text}\nإلى: {new_text}",
        }

    if target_action == "delete_one":
        task_id = str(selected.get("id", "")).strip()
        task_text = str(selected.get("text", "")).strip()
        if not task_id:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {"handled": True, "ok": False, "reply": "ما قدرت أكمل الحذف. جرّب الأمر من جديد."}
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
        return {"handled": True, "reply": f"متأكد بدك أحذف المهمة: {task_text}؟"}

    if target_action == "complete_one":
        task_id = str(selected.get("id", "")).strip()
        task_text = str(selected.get("text", "")).strip()
        if not task_id:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "ما قدرت أكمل المهمة. جرّب الأمر من جديد.",
            }
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
        return {
            "handled": True,
            "reply": f"متأكد بدك أعلّم المهمة كمكتملة؟\n- {task_text}",
        }

    if target_action == "append_note":
        task_id = str(selected.get("id", "")).strip()
        task_text = str(selected.get("text", "")).strip()
        note_text = str(pending.get("note", "")).strip()
        if not task_id or not note_text:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "ما قدرت أكمل إضافة الملاحظة. جرّب الأمر من جديد.",
            }
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "append_note",
                "task_id": task_id,
                "text": task_text,
                "note": note_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        return {
            "handled": True,
            "reply": f"متأكد بدك تضيف هاي الملاحظة للمهمة؟\n- {task_text}\nالملاحظة: {note_text}",
        }

    if target_action == "replace_note":
        task_id = str(selected.get("id", "")).strip()
        task_text = str(selected.get("text", "")).strip()
        note_text = str(pending.get("note", "")).strip()
        if not task_id or not note_text:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "ما قدرت أكمل استبدال الملاحظة. جرّب الأمر من جديد.",
            }
        pending_note_action = "replace_note"
        reply = f"متأكد بدك تستبدل ملاحظة المهمة؟\n- {task_text}\nالملاحظة الجديدة: {note_text}"
        if not _has_visible_task_note(selected):
            pending_note_action = "append_note"
            reply = f"ما في ملاحظة قديمة أستبدلها للمهمة:\n- {task_text}\nبدك أضيف هاي الملاحظة؟\nالملاحظة: {note_text}"
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": pending_note_action,
                "task_id": task_id,
                "text": task_text,
                "note": note_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        return {"handled": True, "reply": reply}

    if target_action == "update_due_date":
        task_id = str(selected.get("id", "")).strip()
        task_text = str(selected.get("text", "")).strip()
        due_iso = str(pending.get("due_iso", "")).strip()
        new_due_text = str(pending.get("new_due_text", "")).strip()
        if str(selected.get("due_at", "")).strip():
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "هاي المهمة فيها وقت/تذكير محفوظ. تعديل تاريخ هالمهام لسا مش جاهز.",
            }
        if not task_id or not due_iso:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "ما قدرت أكمل تعديل التاريخ. جرّب الأمر من جديد.",
            }
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "update_due_date",
                "task_id": task_id,
                "text": task_text,
                "due_iso": due_iso,
                "new_due_text": new_due_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        return {
            "handled": True,
            "reply": f"متأكد بدك تعدّل تاريخ المهمة؟\n- {task_text}\nالتاريخ الجديد: {new_due_text}",
        }

    if target_action == "update_due_time":
        task_id = str(selected.get("id", "")).strip()
        task_text = str(selected.get("text", "")).strip()
        due_iso_for_update = str(pending.get("due_iso", "")).strip()
        time_source = str(pending.get("time_source", "")).strip()

        if not due_iso_for_update:
            base_date = ""
            for source_value in (selected.get("due_at", ""), selected.get("due", "")):
                source_value = str(source_value or "").strip()
                if not source_value:
                    continue
                try:
                    base_dt = datetime.fromisoformat(
                        source_value.replace("Z", "+00:00")
                    )
                    if base_dt.tzinfo is None:
                        base_dt = base_dt.replace(tzinfo=USER_TZ)
                    else:
                        base_dt = base_dt.astimezone(USER_TZ)
                    base_date = base_dt.date().isoformat()
                    break
                except Exception:
                    continue

            has_date_hint = any(
                hint in time_source.lower() for hint in DATE_HINT_TOKENS
            )

            if base_date and not has_date_hint:
                parse_source = f"تاريخ المهمة الحالي هو {base_date}. الوقت الجديد هو {time_source}."
            else:
                parse_source = time_source

            if not parse_source or create_chat_completion_fn is None:
                clear_pending_action(session)
                save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
                return {
                    "handled": True, "ok": False,
                    "reply": "ما قدرت أفهم الوقت الجديد. جرّب الأمر من جديد.",
                }

            due_iso_for_update = (
                deps.parse_reminder_time_ai(
                    normalize_user_message(parse_source),
                    create_chat_completion_fn=create_chat_completion_fn,
                )
                or ""
            )

        if not task_id or not due_iso_for_update:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "ما قدرت أكمل تعديل الوقت. جرّب الأمر من جديد.",
            }

        try:
            due_dt = datetime.fromisoformat(due_iso_for_update.replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=USER_TZ)
            else:
                due_dt = due_dt.astimezone(USER_TZ)

            if due_dt <= datetime.now(USER_TZ):
                clear_pending_action(session)
                save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
                return {
                    "handled": True, "ok": False,
                    "reply": "الوقت الجديد بالماضي. أعطني وقت لاحق.",
                }

            due_iso_for_update = due_dt.isoformat()
            new_due_text = due_dt.strftime("%d/%m/%Y %I:%M %p")

        except Exception:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "الوقت الجديد غير صالح. اكتب الوقت بشكل أوضح.",
            }

        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "update_due_time",
                "task_id": task_id,
                "text": task_text,
                "due_iso": due_iso_for_update,
                "new_due_text": new_due_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        return {
            "handled": True,
            "reply": f"متأكد بدك تعدّل وقت تذكير المهمة؟\n- {task_text}\nالوقت الجديد: {new_due_text}",
        }

    clear_pending_action(session)
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    return {"handled": True, "ok": False, "reply": "نوع الاختيار غير مدعوم حالياً."}


def _handle_clarify_task_write(
    user_message: str,
    pending: Dict[str, Any],
) -> Dict[str, Any]:
    if _is_quick_confirmation(user_message):
        return {
            "handled": True,
            "reply": str(pending.get("repeat_reply", "اكتب التوضيح المطلوب.")).strip()
            or "اكتب التوضيح المطلوب.",
        }
    return {"handled": False}


def _handle_confirm_task_due_date(
    user_message: str,
    pending: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    save_session_fn,
) -> Dict[str, Any]:
    if _is_quick_confirmation(user_message):
        task_text = str(pending.get("task_text", "")).strip()
        suggested_iso = str(pending.get("suggested_iso", "")).strip()
        if not task_text or not suggested_iso:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {
                "handled": True, "ok": False,
                "reply": "ما قدرت أكمل إضافة المهمة. جرّب من جديد.",
            }
        try:
            due_dt = datetime.fromisoformat(suggested_iso.replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=USER_TZ)
            else:
                due_dt = due_dt.astimezone(USER_TZ)
            if due_dt.hour == 0 and due_dt.minute == 0 and due_dt.second == 0:
                due_dt = due_dt.replace(hour=11, minute=0, second=0, microsecond=0)
            if due_dt <= datetime.now(USER_TZ):
                clear_pending_action(session)
                save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
                return {
                    "handled": True, "ok": False,
                    "reply": "موعد المهمة صار بالماضي. أعطني وقت لاحق.",
                }
            task_id = deps.add_task(
                task_text,
                due_iso=due_dt.isoformat(),
                mongo_db=mongo_db,
                tasks_file=tasks_file,
            )
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            if task_id:
                due_text = due_dt.strftime("%d/%m/%Y")
                return {
                    "handled": True,
                    "reply": f"تم التسجيل. المهمة محفوظة؛ الاستحقاق: {due_text}",
                }
            return {"handled": True, "ok": False, "reply": "صار خطأ وأنا بحفظ المهمة."}
        except Exception as e:
            clear_pending_action(session)
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
            return {"handled": True, "ok": False,
                    "error": f"confirm_task_due_date: {type(e).__name__}",
                    "reply": f"ما قدرت أكمل: {str(e)[:50]}"}
    elif is_cancellation(user_message):
        clear_pending_action(session)
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        return {"handled": True, "reply": "تمام، لغيت إضافة المهمة."}
    return {"handled": False}
