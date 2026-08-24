"""Task tools — schemas + adapters لـ ToolRegistry.

كل tool = schema (لـ Gemini) + adapter (يستدعي handle_task_action).
"""

from __future__ import annotations
import logging

from typing import TYPE_CHECKING, Any, Dict, List

from app.agent.tool_result import result_ok

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext

def _NOOP_SAVE(*a, **kw): return None


def _persona_intensity(ctx: "DispatchContext") -> str:
    """نبرة Sandy الحالية من الـ state (يحطها soul_node قبل execute)."""
    try:
        if ctx.state:
            return ctx.state.get("persona_intensity") or "standard"
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
    return "standard"


def _task_create_reply(titles: List[str], due: str = "", intensity: str = "standard") -> str:
    """يبني تأكيد إنشاء المهام محلياً من response_templates، بدون استدعاء LLM.

    يدعم عنوان واحد أو عدة عناوين. النبرة تتبع مزاج Sandy الحالي، ولو ما في
    قالب للنبرة المطلوبة بيرجع للـ standard.
    """
    from app.agent.graph.response_templates import get_response_template

    intro = get_response_template("task.create", intensity) or "سجّلتها"
    due_part = f" بموعد {due}" if due else ""
    if len(titles) == 1:
        return f"{intro} '{titles[0]}'{due_part}."
    listed = "، ".join(f"'{t}'" for t in titles)
    return f"{intro} {len(titles)} مهام: {listed}{due_part}."


def _with_alerts(reply: str, alerts: List[str]) -> str:
    """Re-attach anything the handler produced that this adapter cannot rebuild.

    `task_create` replaces the handler's sentence with a persona-toned one, and
    that used to throw away the scheduling-conflict warning built next to it —
    the one piece of that reply carrying information rather than tone. The
    handler hands it over as `alert` so overwriting the prose stops costing it.
    """
    if not alerts:
        return reply
    return reply + "".join(f"\n\n⚠️ {a}" for a in alerts)


def _call_task(params: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.agent.executor.task_handlers import handle_task_action
    return handle_task_action(
        params,
        user_message=ctx.user_message,
        normalized_user_message=ctx.normalized_message,
        session=ctx.session,
        session_file=None,
        mongo_db=ctx.mongo_db,
        tasks_file=None,
        create_chat_completion_fn=ctx.create_chat_completion_fn,
        save_session_fn=_NOOP_SAVE,
    )


# Adapters

def task_create(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    titles = args.get("titles")
    due = args.get("due", "")
    extras = {
        "priority": args.get("priority", ""),
        "project": args.get("project", ""),
    }
    intensity = _persona_intensity(ctx)
    # الجملة الجاهزة بتنكتب فوق ردّ المنفّذ، فلازم تنكتب على النجاح فقط.
    # كانت بتتبع `handled`، والرفض `handled=True` كمان — فطلب ثلاث مهام
    # وكتابة فاشلة كان يطلع «سجّلتها ✅ 3 مهام» وما ينكتب ولا صف.
    if isinstance(titles, list):
        wanted = [str(t).strip() for t in titles if str(t).strip()]
        if not wanted:
            # قايمة فاضية أو كلها فراغات — كانت بتنزل لمسار العنوان المفرد
            # وتطلع «سجّلتها ✅ ''».
            return {"handled": True, "ok": False,
                    "reply": "شو المهام اللي بدك أضيفها؟"}
        created, failed, alerts = [], [], []
        refusal = None
        for t in wanted:
            r = _call_task({"action": "create", "text": t, "due_text": due, "notes": args.get("notes", ""), **extras}, ctx)
            if result_ok(r):
                created.append(t)
                if r.get("alert"):
                    alerts.append(str(r["alert"]))
            else:
                failed.append(t)
                if refusal is None:
                    refusal = r
        if not created:
            # ما انكتبت ولا وحدة — رجّع سبب أول رفض بدل «تم.» الصامتة.
            return {"handled": True, "ok": False,
                    "reply": (refusal or {}).get("reply") or "ما قدرت أضيف المهام."}
        reply = _task_create_reply(created, due, intensity)
        if failed:
            # النجاح الجزئي لازم يقول شو ضاع. بدون هالسطر بيطلب تلاتة، بيسمع
            # عن تنتين، وما بيعرف أبداً إنه في وحدة ما انكتبت.
            listed = "، ".join(f"'{t}'" for t in failed)
            why = str((refusal or {}).get("reply") or "").strip()
            reply += f"\nبس ما قدرت أضيف: {listed}." + (f" {why}" if why else "")
        return {"handled": True, "ok": not failed,
                "reply": _with_alerts(reply, alerts)}
    result = _call_task({
        "action": "create",
        "text": args.get("title", ""),
        "due_text": due,
        "notes": args.get("notes", ""),
        **extras,
    }, ctx)
    if result_ok(result):
        result["reply"] = _with_alerts(
            _task_create_reply([args.get("title", "")], due, intensity),
            [str(result["alert"])] if result.get("alert") else [],
        )
    return result

def task_list(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    filter_type = str(args.get("filter") or "active").lower()
    action_map = {
        "completed": "list_completed",
        "all": "list_all",
        "overdue": "list_overdue",
    }
    return _call_task({"action": action_map.get(filter_type, "list")}, ctx)

def task_complete(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    # إقرار هادي مش احتفال: شطب مهمة بيصير عشر مرّات باليوم، والاحتفال الكامل
    # بيفقد معناه لو صار روتين. الاحتفال محجوز للأهداف وسلاسل الأسبوع.
    from app.features.robot_expression import acknowledge

    if args.get("all"):
        r = _call_task({"action": "complete_all"}, ctx)
    else:
        refs = args.get("references")
        if refs and isinstance(refs, list):
            r = _call_task({"action": "complete_multi",
                            "reference": " ".join(str(x) for x in refs)}, ctx)
        else:
            r = _call_task({"action": "complete", "reference": args.get("reference", "")}, ctx)
    if result_ok(r):
        acknowledge()
    return r

def task_uncomplete(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_task({"action": "uncomplete", "reference": args.get("reference", "")}, ctx)

def task_delete(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    if args.get("scope") == "completed":
        return _call_task({"action": "delete_completed"}, ctx)
    if args.get("all"):
        return _call_task({"action": "delete_all"}, ctx)
    refs = args.get("references")
    if refs and isinstance(refs, list):
        return _call_task({"action": "delete_multi", "reference": " ".join(str(r) for r in refs)}, ctx)
    return _call_task({"action": "delete", "reference": args.get("reference", "")}, ctx)

def task_update(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    ref = args.get("reference", "")
    if args.get("title"):
        return _call_task({"action": "rename", "reference": ref, "text": args["title"]}, ctx)
    if args.get("notes"):
        return _call_task({"action": "append_note", "reference": ref, "notes": args["notes"]}, ctx)
    if args.get("due"):
        return _call_task({"action": "update_due_date", "reference": ref, "due_text": args["due"]}, ctx)
    return {"handled": False, "reply": "حدّد ما تريد تعديله (عنوان/ملاحظة/موعد)."}


# Schemas

TASK_TOOLS = [
    {
        "name": "task_create",
        "description": "أضف مهمة أو عدة مهام — استخدم titles=[...] لإضافة أكثر من مهمة دفعة واحدة",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "عنوان المهمة (لمهمة واحدة)"},
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "قائمة عناوين لإضافة عدة مهام دفعة واحدة",
                },
                "notes": {"type": "string", "description": "ملاحظة اختيارية"},
                "due": {"type": "string", "description": "تاريخ الاستحقاق (ISO أو وصف مثل 'بكرا')"},
                "priority": {"type": "string", "description": "الأولوية: high | normal | low (اختياري)"},
                "project": {"type": "string", "description": "اسم المشروع/المجموعة اللي تنتمي لها المهمة (اختياري)"},
            },
            "required": [],
        },
        "handler": task_create,
    },
    {
        "name": "task_list",
        "description": "اعرض قائمة المهام",
        "parameters": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "active (default) | completed | all | overdue",
                },
            },
            "required": [],
        },
        "handler": task_list,
    },
    {
        "name": "task_complete",
        "description": "اعلم مهمة أو أكثر كمكتملة — استخدم all=true لإكمال جميع المهام (يطلب تأكيداً تلقائياً، لا تستخدم request_confirmation)",
        "parameters": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "رقم أو عنوان المهمة"},
                "references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "قائمة مهام لإكمالها دفعة واحدة",
                },
                "all": {"type": "boolean", "description": "true لإكمال جميع المهام"},
            },
            "required": [],
        },
        "handler": task_complete,
    },
    {
        "name": "task_uncomplete",
        "description": "أعد مهمة للقائمة النشطة",
        "parameters": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "رقم أو عنوان المهمة"},
            },
            "required": ["reference"],
        },
        "handler": task_uncomplete,
    },
    {
        "name": "task_delete",
        "description": "احذف مهمة أو أكثر أو جميع المهام — استخدم all=true لحذف الكل، scope='completed' لحذف المكتملة فقط (يطلب تأكيداً تلقائياً، لا تستخدم request_confirmation)",
        "parameters": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "رقم أو عنوان المهمة"},
                "references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "قائمة مهام للحذف دفعة واحدة",
                },
                "all": {"type": "boolean", "description": "true لحذف جميع المهام النشطة"},
                "scope": {"type": "string", "description": "completed لحذف المهام المكتملة فقط"},
            },
            "required": [],
        },
        "handler": task_delete,
    },
    {
        "name": "task_update",
        "description": "عدّل عنوان أو ملاحظة أو موعد استحقاق مهمة",
        "parameters": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "رقم أو عنوان المهمة"},
                "title": {"type": "string", "description": "العنوان الجديد"},
                "notes": {"type": "string", "description": "ملاحظة تُضاف"},
                "due": {"type": "string", "description": "موعد الاستحقاق الجديد"},
            },
            "required": ["reference"],
        },
        "handler": task_update,
    },
]
