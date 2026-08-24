"""Task creation handlers."""
from datetime import datetime
from typing import Any, Dict


from app.utils.nlp_normalizer import normalize_user_message
from app.utils.time import USER_TZ
from app.agent.pending import create_pending_action
from app.agent.deep_context import record_last_action
from app.agent.conflict_resolution import run_conflict_check_after_task_add

from app.features.time_parser import (
    parse_reminder_time_ai,
)
from app.features.tasks_store import (
    add_task,
)




def _handle_create(
    task_text: str,
    task_due_iso: str,
    task_due_text: str,
    task_notes: str,
    task_priority: str = "",
    task_project: str = "",
    *,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    create_chat_completion_fn,
    save_session_fn,
) -> Dict[str, Any]:
    ok = True
    conflict_alert = ""
    if not task_text:
        # سؤال، بس ما في `pending` بيحمله للدور الجاي — يعني المعالجة خلصت
        # وما انكتب إشي. بدون `ok=False` المحوّل فوق بيكتب فوقه «سجّلتها ✅ ''».
        return {"handled": True, "ok": False,
                "reply": "شو المهمة اللي بدك أضيفها؟"}

    if not task_due_iso and task_due_text:
        due_parse_source = normalize_user_message(task_due_text)
        parsed_due = parse_reminder_time_ai(
            due_parse_source,
            create_chat_completion_fn=create_chat_completion_fn,
            return_json=True,
        )
        if isinstance(parsed_due, dict):
            if parsed_due.get("success"):
                task_due_iso = parsed_due.get("remind_at_iso") or ""
            else:
                suggested = parsed_due.get("suggested_iso")
                if suggested:
                    try:
                        sdt = datetime.fromisoformat(suggested.replace("Z", "+00:00"))
                        if sdt.tzinfo is not None:
                            sdt = sdt.astimezone(USER_TZ)
                        confirm_text = sdt.strftime("%d/%m/%Y")
                    except Exception:
                        confirm_text = suggested
                    session["pending_action"] = create_pending_action(
                        {
                            "type": "task",
                            "action": "confirm_task_due_date",
                            "task_text": task_text,
                            "suggested_iso": suggested,
                            "confirmation_status": "pending",
                        }
                    )
                    save_session_fn(
                        session, session_file=session_file, mongo_db=mongo_db
                    )
                    return {
                        "handled": True,
                        "reply": f"ما فهمت موعد المهمة بدقّة. تقصد تضيف المهمة ليوم {confirm_text}?",
                    }
        else:
            task_due_iso = parsed_due or ""

        if not task_due_iso:
            return {
                "handled": True, "ok": False,
                "reply": "في موعد للمهمة لكن ما فهمته بدقة. اكتب التاريخ أو الوقت بشكل أوضح.",
            }

    if task_due_iso:
        try:
            due_dt = datetime.fromisoformat(task_due_iso.replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=USER_TZ)
            else:
                due_dt = due_dt.astimezone(USER_TZ)

            # Midnight means no time was given (date-only ISO, or AI due_iso
            # without a time), so default to 11:00 AM.
            if due_dt.hour == 0 and due_dt.minute == 0 and due_dt.second == 0:
                due_dt = due_dt.replace(hour=11, minute=0, second=0, microsecond=0)

            if due_dt <= datetime.now(USER_TZ):
                return {
                    "handled": True, "ok": False,
                    "reply": "موعد المهمة صار بالماضي، أعطني وقت لاحق.",
                }

            task_due_iso = due_dt.isoformat()
        except Exception:
            return {
                "handled": True, "ok": False,
                "reply": "وقت المهمة غير صالح. اكتب التاريخ أو الوقت بشكل أوضح.",
            }

    task_id = add_task(
        task_text,
        due_iso=task_due_iso,
        notes=task_notes,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        priority=task_priority,
        project=task_project,
    )
    if task_id:
        session["_last_created_task_id"] = task_id
        session["_last_created_task_text"] = task_text
        record_last_action(
            session,
            "task_created",
            summary=task_text,
            refs={"task_id": task_id, "task_text": task_text},
        )
        if task_due_iso:
            reply = "تم التسجيل. المهمة محفوظة مع استحقاق."
            conflict_result = run_conflict_check_after_task_add(
                task_id=task_id,
                task_text=task_text,
                due_iso=task_due_iso,
                notes=task_notes,
                mongo_db=mongo_db,
                tasks_file=tasks_file,
            )
            if isinstance(conflict_result, str):
                conflict_alert = conflict_result
            else:
                conflict_alert = str(
                    (conflict_result or {}).get("alert_text", "") or ""
                )
            if conflict_alert:
                reply = f"{reply}\n\n⚠️ {conflict_alert}"
        else:
            reply = "تم التسجيل. المهمة محفوظة."
    else:
        reply = "ما قدرت أضيف المهمة."
        ok = False
    # التنبيه بحقل لحاله كمان.
    #
    # `task_tools.task_create` بتكتب فوق `reply` بجملة بنبرة ساندي، فتحذير
    # التعارض — وهو الإشي الوحيد هون اللي المحوّل ما بيقدر يعيد بناءه — كان
    # بينمسح كل مرة. النصّ ملك المحوّل، والتحذير ملك المعالج.
    out: Dict[str, Any] = {"handled": True, "ok": ok, "reply": reply}
    if conflict_alert:
        out["alert"] = conflict_alert
    return out
