"""Task due_date handlers."""
from datetime import datetime
from typing import Any, Dict


from app.utils.arabic_days import DATE_HINT_TOKENS
from app.utils.nlp_normalizer import normalize_user_message
from app.utils.time import USER_TZ
from app.agent.pending import create_pending_action

from app.features.time_parser import (
    parse_reminder_time_ai,
)
from app.features.tasks_store import (
    load_tasks,
    resolve_task_reference_for_write,
)


from app.agent.executor.task_handlers._common import (
    _format_task_choices,
)


def _handle_update_due_date(
    task_reference: str,
    task_due_iso: str,
    task_due_text: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    create_chat_completion_fn,
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
        reply = "ما لقيت هاي المهمة ضمن المهام النشطة. اعرض المهام مرة ثانية واختر مهمة موجودة."

    elif status == "ambiguous":
        due_iso_for_update = task_due_iso

        if not due_iso_for_update and task_due_text:
            parsed = parse_reminder_time_ai(
                normalize_user_message(task_due_text),
                create_chat_completion_fn=create_chat_completion_fn,
                return_json=True,
            )
            if isinstance(parsed, dict):
                if parsed.get("success"):
                    due_iso_for_update = parsed.get("remind_at_iso") or ""
                else:
                    suggested = parsed.get("suggested_iso")
                    if suggested:
                        try:
                            sdt = datetime.fromisoformat(
                                suggested.replace("Z", "+00:00")
                            )
                            if sdt.tzinfo is not None:
                                sdt = sdt.astimezone(USER_TZ)
                            confirm_text = sdt.strftime("%d/%m/%Y")
                        except Exception:
                            confirm_text = suggested
                        return {
                            "handled": True,
                            "reply": f"ما فهمت التاريخ بدقّة. تقصد اختار المهمة وعدّل التاريخ ليوم {confirm_text}?",
                        }
            else:
                due_iso_for_update = parsed or ""

        if not due_iso_for_update:
            return {
                "handled": True,
                "reply": "ما فهمت التاريخ الجديد بدقة. اكتب التاريخ بشكل أوضح.",
            }

        try:
            due_dt = datetime.fromisoformat(due_iso_for_update.replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=USER_TZ)
            else:
                due_dt = due_dt.astimezone(USER_TZ)

            if due_dt.date() < datetime.now(USER_TZ).date():
                return {
                    "handled": True,
                    "reply": "التاريخ الجديد بالماضي. أعطني تاريخ اليوم أو تاريخ لاحق.",
                }

            due_iso_for_update = due_dt.isoformat()
            new_due_text = due_dt.strftime("%d/%m/%Y")

        except Exception:
            return {
                "handled": True,
                "reply": "التاريخ الجديد غير صالح. اكتب التاريخ بشكل أوضح.",
            }

        choices = [
            {
                "id": task.get("id", ""),
                "text": task.get("text", ""),
                "due_at": task.get("due_at", ""),
            }
            for task in result.get("matches", [])[:5]
            if task.get("id")
        ]

        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "clarify_task_choice",
                "target_action": "update_due_date",
                "choices": choices,
                "due_iso": due_iso_for_update,
                "new_due_text": new_due_text,
                "confirmation_status": "clarification",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)

        reply = (
            "لقيت أكثر من مهمة مطابقة:\n"
            + _format_task_choices(choices)
            + "\nاختار واحدة: الأولى، الثانية، أو رقم المهمة."
        )

    elif task_obj:
        if str(task_obj.get("due_at", "")).strip():
            reply = "هاي المهمة لسا مش جاهزة"
        else:
            due_iso_for_update = task_due_iso

            if not due_iso_for_update and task_due_text:
                parsed = parse_reminder_time_ai(
                    normalize_user_message(task_due_text),
                    create_chat_completion_fn=create_chat_completion_fn,
                    return_json=True,
                )
                if isinstance(parsed, dict):
                    if parsed.get("success"):
                        due_iso_for_update = parsed.get("remind_at_iso") or ""
                    else:
                        suggested = parsed.get("suggested_iso")
                        if suggested:
                            try:
                                sdt = datetime.fromisoformat(
                                    suggested.replace("Z", "+00:00")
                                )
                                if sdt.tzinfo is not None:
                                    sdt = sdt.astimezone(USER_TZ)
                                confirm_text = sdt.strftime("%d/%m/%Y")
                            except Exception:
                                confirm_text = suggested
                            return {
                                "handled": True,
                                "reply": f"ما فهمت التاريخ بدقّة. تقصد اختار المهمة وعدّل التاريخ ليوم {confirm_text}?",
                            }
                else:
                    due_iso_for_update = parsed or ""

            if not due_iso_for_update:
                return {
                    "handled": True,
                    "reply": "ما فهمت التاريخ الجديد بدقة. اكتب التاريخ بشكل أوضح.",
                }

            try:
                due_dt = datetime.fromisoformat(
                    due_iso_for_update.replace("Z", "+00:00")
                )
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=USER_TZ)
                else:
                    due_dt = due_dt.astimezone(USER_TZ)

                if due_dt.date() < datetime.now(USER_TZ).date():
                    return {
                        "handled": True,
                        "reply": "التاريخ الجديد بالماضي. أعطني تاريخ اليوم أو تاريخ لاحق.",
                    }

                due_iso_for_update = due_dt.isoformat()
                new_due_text = due_dt.strftime("%d/%m/%Y")

            except Exception:
                return {
                    "handled": True,
                    "reply": "التاريخ الجديد غير صالح. اكتب التاريخ بشكل أوضح.",
                }

            task_text_current = task_obj.get("text", "")

            session["pending_action"] = create_pending_action(
                {
                    "type": "task",
                    "action": "update_due_date",
                    "task_id": task_obj.get("id", ""),
                    "text": task_text_current,
                    "due_iso": due_iso_for_update,
                    "new_due_text": new_due_text,
                    "confirmation_status": "pending",
                }
            )
            save_session_fn(session, session_file=session_file, mongo_db=mongo_db)

            reply = f"متأكد بدك تعدّل تاريخ المهمة؟\n- {task_text_current}\nالتاريخ الجديد: {new_due_text}"

    else:
        reply = "ما قدرت أحدد المهمة."

    return {"handled": True, "reply": reply}




def _handle_update_due_time(
    task_reference: str,
    task_due_iso: str,
    task_due_text: str,
    task_time_text: str,
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    create_chat_completion_fn,
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
        reply = "ما لقيت هاي المهمة ضمن المهام النشطة. اعرض المهام مرة ثانية واختر مهمة موجودة."

    elif status == "ambiguous":
        time_source = task_time_text or task_due_text

        if not task_due_iso and not time_source:
            return {
                "handled": True,
                "reply": "ما فهمت الوقت الجديد بدقة. اكتب الوقت بشكل أوضح.",
            }

        choices = [
            {
                "id": task.get("id", ""),
                "text": task.get("text", ""),
                "due": task.get("due", ""),
                "due_at": task.get("due_at", ""),
            }
            for task in result.get("matches", [])[:5]
            if task.get("id")
        ]

        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "clarify_task_choice",
                "target_action": "update_due_time",
                "choices": choices,
                "due_iso": task_due_iso,
                "time_source": time_source,
                "confirmation_status": "clarification",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)

        reply = (
            "لقيت أكثر من مهمة مطابقة:\n"
            + _format_task_choices(choices)
            + "\nاختار واحدة: الأولى، الثانية، أو رقم المهمة."
        )

    elif task_obj:
        due_iso_for_update = task_due_iso

        if not due_iso_for_update:
            base_date = ""

            for source_value in (task_obj.get("due_at", ""), task_obj.get("due", "")):
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

            time_source = task_time_text or task_due_text

            has_date_hint = any(
                hint in time_source.lower() for hint in DATE_HINT_TOKENS
            )

            if base_date and not has_date_hint:
                parse_source = f"تاريخ المهمة الحالي هو {base_date}. الوقت الجديد هو {time_source}."
            else:
                parse_source = time_source

            parsed = parse_reminder_time_ai(
                normalize_user_message(parse_source),
                create_chat_completion_fn=create_chat_completion_fn,
                return_json=True,
            )
            if isinstance(parsed, dict):
                if parsed.get("success"):
                    due_iso_for_update = parsed.get("remind_at_iso") or ""
                else:
                    suggested = parsed.get("suggested_iso")
                    if suggested:
                        try:
                            sdt = datetime.fromisoformat(
                                suggested.replace("Z", "+00:00")
                            )
                            if sdt.tzinfo is not None:
                                sdt = sdt.astimezone(USER_TZ)
                            confirm_text = sdt.strftime("%d/%m/%Y %I:%M %p")
                        except Exception:
                            confirm_text = suggested
                        return {
                            "handled": True,
                            "reply": f"ما فهمت الوقت بدقّة. تقصد تعدّل وقت المهمة ليوم {confirm_text}?",
                        }
            else:
                due_iso_for_update = parsed or ""

        if not due_iso_for_update:
            return {
                "handled": True,
                "reply": "ما فهمت الوقت الجديد بدقة. اكتب الوقت بشكل أوضح.",
            }

        try:
            due_dt = datetime.fromisoformat(due_iso_for_update.replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=USER_TZ)
            else:
                due_dt = due_dt.astimezone(USER_TZ)

            if due_dt <= datetime.now(USER_TZ):
                return {
                    "handled": True,
                    "reply": "الوقت الجديد بالماضي. أعطني وقت لاحق.",
                }

            due_iso_for_update = due_dt.isoformat()
            new_due_text = due_dt.strftime("%d/%m/%Y %I:%M %p")

        except Exception:
            return {
                "handled": True,
                "reply": "الوقت الجديد غير صالح. اكتب الوقت بشكل أوضح.",
            }

        task_text_current = task_obj.get("text", "")

        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "update_due_time",
                "task_id": task_obj.get("id", ""),
                "text": task_text_current,
                "due_iso": due_iso_for_update,
                "new_due_text": new_due_text,
                "confirmation_status": "pending",
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)

        reply = f"متأكد بدك تعدّل وقت تذكير المهمة؟\n- {task_text_current}\nالوقت الجديد: {new_due_text}"

    else:
        reply = "ما قدرت أحدد المهمة."

    return {"handled": True, "reply": reply}




def _handle_bulk_update_due_date(
    params: Dict[str, Any],
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    create_chat_completion_fn,
    save_session_fn,
) -> Dict[str, Any]:
    from_due_text = str(params.get("from_due_text", "")).strip()
    to_due_text = str(params.get("to_due_text", "")).strip()

    if not from_due_text or not to_due_text:
        return {"handled": True, "reply": "مش واضح: من أي تاريخ وإلى أي تاريخ؟"}

    parsed_to = parse_reminder_time_ai(
        normalize_user_message(to_due_text),
        create_chat_completion_fn=create_chat_completion_fn,
        return_json=True,
    )
    if isinstance(parsed_to, dict):
        if parsed_to.get("success"):
            to_due_iso = parsed_to.get("remind_at_iso") or ""
        else:
            suggested = parsed_to.get("suggested_iso")
            if suggested:
                try:
                    sdt = datetime.fromisoformat(suggested.replace("Z", "+00:00"))
                    if sdt.tzinfo is not None:
                        sdt = sdt.astimezone(USER_TZ)
                    confirm_text = sdt.strftime("%d/%m/%Y")
                except Exception:
                    confirm_text = suggested
                return {
                    "handled": True,
                    "reply": f"ما فهمت التاريخ الجديد. تقصد تؤجّل المهام ليوم {confirm_text}?",
                }
            else:
                return {
                    "handled": True,
                    "reply": f"ما فهمت التاريخ الجديد: '{to_due_text}'. حدد التاريخ بوضوح.",
                }
    else:
        to_due_iso = parsed_to or ""

    if not to_due_iso:
        return {
            "handled": True,
            "reply": f"ما فهمت التاريخ الجديد: '{to_due_text}'. حدد التاريخ بوضوح.",
        }

    try:
        to_dt = datetime.fromisoformat(to_due_iso.replace("Z", "+00:00"))
        if to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=USER_TZ)
        else:
            to_dt = to_dt.astimezone(USER_TZ)
        if to_dt.date() < datetime.now(USER_TZ).date():
            return {
                "handled": True,
                "reply": "التاريخ الجديد في الماضي. أعطني تاريخ اليوم أو لاحق.",
            }
        to_due_iso = to_dt.isoformat()
        to_due_display = to_dt.strftime("%d/%m/%Y")
    except Exception:
        return {"handled": True, "reply": "التاريخ الجديد غير صالح."}

    parsed_from = parse_reminder_time_ai(
        normalize_user_message(from_due_text),
        create_chat_completion_fn=create_chat_completion_fn,
        return_json=True,
    )
    if isinstance(parsed_from, dict):
        if parsed_from.get("success"):
            from_due_iso = parsed_from.get("remind_at_iso") or ""
        else:
            suggested = parsed_from.get("suggested_iso")
            if suggested:
                try:
                    sdt = datetime.fromisoformat(suggested.replace("Z", "+00:00"))
                    if sdt.tzinfo is not None:
                        sdt = sdt.astimezone(USER_TZ)
                    confirm_text = sdt.strftime("%d/%m/%Y")
                except Exception:
                    confirm_text = suggested
                return {
                    "handled": True,
                    "reply": f"ما فهمت تاريخ البحث. تقصد البحث عن مهام من تاريخ {confirm_text}?",
                }
            else:
                return {
                    "handled": True,
                    "reply": f"ما فهمت تاريخ البحث: '{from_due_text}'. حدد التاريخ بوضوح.",
                }
    else:
        from_due_iso = parsed_from or ""

    if not from_due_iso:
        return {
            "handled": True,
            "reply": f"ما فهمت تاريخ البحث: '{from_due_text}'. حدد التاريخ بوضوح.",
        }

    try:
        from_dt = datetime.fromisoformat(from_due_iso.replace("Z", "+00:00"))
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=USER_TZ)
        from_date_str = from_dt.date().isoformat()
    except Exception:
        return {"handled": True, "reply": "تاريخ البحث غير صالح."}

    all_tasks = load_tasks(mongo_db=mongo_db, tasks_file=tasks_file)
    matching_tasks = [
        {"id": t.get("id", ""), "text": t.get("text", "")}
        for t in all_tasks
        if str(t.get("due", "") or "").strip().startswith(from_date_str) and t.get("id")
    ]

    if not matching_tasks:
        return {"handled": True, "reply": f"ما في مهام مستحقة في {from_due_text}."}

    lines = "\n".join(f"- {t['text']}" for t in matching_tasks)
    session["pending_action"] = create_pending_action(
        {
            "type": "task",
            "action": "bulk_update_due_date",
            "tasks": matching_tasks,
            "to_due_iso": to_due_iso,
            "to_due_text": to_due_display,
            "confirmation_status": "pending",
        }
    )
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    return {
        "handled": True,
        "reply": f"بدي أؤجل {len(matching_tasks)} مهام من {from_due_text} إلى {to_due_display}:\n{lines}\nموافق؟",
    }
