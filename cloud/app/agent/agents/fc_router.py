"""Function-calling routing for Sandy.

One native function-calling pass: the model sees every tool as a real tool
(name + description + JSON-Schema params) and either calls the right one(s) or
replies in plain text (→ chat). No hand-written example prompt, no JSON-by-string
parsing — the model picks from the real schemas, which is both faster (one call)
and more accurate than the old 200-line disambiguation prompt.

Mood + face are derived from the picked tool via a cheap table (no extra call);
the actual reply persona still comes from the soul node downstream.

Caching note (R3): the stable prefix — tool catalog + persona/rules system — is
sent first and kept identical across turns, so Azure prompt caching keeps biting.
Only the per-turn user block (message + history + live device list) varies.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.agent.command_rules import DISAMBIGUATION_RULES_AR
from app.agent.graph.state import SandyState, merge_state
# Destructive-tool set lives in app.agent.guards so the text router and the voice
# path (Track 4.2) share one definition (see Track 1.2).
from app.agent.guards import DESTRUCTIVE_TOOLS as _DESTRUCTIVE_TOOLS
from app.integrations.azure_intent_client import AzureIntentClient
from app.utils.user_profiles import address_instruction

logger = logging.getLogger(__name__)


# Handled by routing logic, not the ToolDispatcher.
_META_TOOL_NAMES = frozenset({
    "ask_clarification",
    "request_confirmation",
    "chat_respond",
    "chat_emotional",
    "pending_confirm",
    "pending_reject",
    "pending_select",
})

_FC_DEFAULT_CALL = {"name": "chat_respond", "args": {"type": "general"}}

# Routing-only meta-tools, in native function-calling shape. They never reach the
# ToolDispatcher — the graph turns them into chat / clarify / pending flows.
_META_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "chat_respond",
        "description": "دردشة عامة، تحية، شكر، أو لا يوجد طلب/أمر واضح",
        "parameters": {
            "type": "object",
            "properties": {"type": {"type": "string", "description": "نوع الدردشة"}},
        },
    },
    {
        "name": "chat_emotional",
        "description": "دعم عاطفي عندما يكون المستخدم متوتراً/محبَطاً/حزيناً",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "ask_clarification",
        "description": "اسأل سؤالاً توضيحياً فقط عند غموض كامل (لا object إطلاقاً)",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "request_confirmation",
        "description": (
            "اطلب تأكيداً قبل تنفيذ عملية خطيرة/لا رجعة فيها عندما يكون الهدف غير "
            "واضح صراحةً (عدا task_delete وtask_complete — لهم تأكيد تلقائي)"
        ),
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
    {
        "name": "pending_confirm",
        "description": "المستخدم وافق على pending نشط (تمام/اه/أوكي)",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "pending_reject",
        "description": "المستخدم رفض pending نشط (لأ/خلص/الغي)",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "pending_select",
        "description": "المستخدم اختار خياراً من pending نشط (رقم/اسم)",
        "parameters": {
            "type": "object",
            "properties": {"choice": {"type": "string"}},
            "required": ["choice"],
        },
    },
]

_ROUTER_SYSTEM = """\
أنت طبقة فهم النية لمساعدة اسمها Sandy. مهمتك: اقرأ رسالة المستخدم واستدعِ الأداة \
الصحيحة من الأدوات المتاحة، أو ردّ نصياً عادياً إذا كانت مجرد دردشة.

مبادئ:
- رسالة فيها فعل + object واضح (اعملي/احذفي/غيّري/اعرضي/ذكّريني + مهمة/موعد/تذكير/صورة…) \
→ استدعِ الأداة المخصصة لها مباشرةً. لا تردّ نصياً في هذه الحالة.
- تحية أو شكر أو سؤال عام أو كلام بلا طلب تنفيذي → استدعِ chat_respond (أو ردّ نصياً).
- لا تستنتج من المحادثة القديمة أن المستخدم يريد إعادة طلب سابق — الرسالة الحالية حصراً.
- إذا الرسالة الحالية وحدها فيها طلبان مستقلان أو أكثر → استدعِ أداة لكل طلب.
- النفي يقلب المعنى: "ما/مش/بطّلي/الغي + تذكير/موعد" = حذف، وليس إنشاء.
- "احذفي الموعد" → reminder_delete، و"احذفي المهمة" → task_delete (لا تخلط بينهما).
- حدث له وقت/تاريخ ولو بصيغة ضمنية ("عندي مقابلة الأربعاء") → reminder_create.
- التفاصيل الناقصة ليست سبباً للسؤال: نادِ الأداة، الـ handler يكمل. \
ask_clarification هي الملاذ الأخير عند الغموض الكامل فقط.
- للعمليات الخطيرة/الفيزيائية (حذف، تحكّم بجهاز، تطبيق مشهد) إذا الهدف غير واضح صراحةً \
→ استدعِ request_confirmation بدل تنفيذها مباشرةً.
- إذا في pending نشط ورد المستخدم قصير (تمام/لأ/رقم) → pending_confirm | pending_reject | pending_select.

اختر الأداة من تعريفها الحقيقي. ردودك النصية (عند الدردشة) موجزة ودافئة."""


def _build_native_tools(declarations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wrap registry declarations + the meta-tools into native FC tool specs.

    Kept identical turn-to-turn (declarations are static) so it sits in the
    cached prefix.
    """
    specs = list(declarations) + _META_TOOL_SPECS
    tools = []
    for d in specs:
        name = d.get("name")
        if not name:
            continue
        params = d.get("parameters") or {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": d.get("description", ""),
                "parameters": params,
            },
        })
    return tools


def _parse_tool_message(msg: Any) -> List[Dict[str, Any]]:
    """Pull {name, args} calls out of a native tool message.

    No tool calls → the model chose to chat: return chat_respond.
    """
    tool_calls = getattr(msg, "tool_calls", None) if msg is not None else None
    if not tool_calls:
        return [dict(_FC_DEFAULT_CALL)]

    calls: List[Dict[str, Any]] = []
    for tc in tool_calls:
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None) if fn else None
        if not name:
            continue
        raw_args = getattr(fn, "arguments", None) if fn else None
        args: Dict[str, Any] = {}
        if raw_args:
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    args = parsed
            except (json.JSONDecodeError, ValueError):
                args = {}
        calls.append({"name": str(name), "args": args})

    return calls or [dict(_FC_DEFAULT_CALL)]


# Cheap, deterministic face/mood from the picked tool — no extra model call.
_CREATE_FACES = frozenset({
    "task_create", "reminder_create", "memory_store", "image_generate",
    "shopping_add", "habit_add", "goal_set", "journal_add", "book_add",
})


def _derive_face_mood(fn_name: str) -> Dict[str, str]:
    """Map the chosen tool to a face + user-mood + persona intensity."""
    if fn_name == "chat_emotional":
        return {"sandy_face": "worried", "mood": "stressed",
                "persona_intensity": "empathetic"}
    if fn_name in _DESTRUCTIVE_TOOLS:
        return {"sandy_face": "focused", "mood": "neutral",
                "persona_intensity": "standard"}
    if fn_name in _CREATE_FACES:
        return {"sandy_face": "happy", "mood": "neutral",
                "persona_intensity": "standard"}
    if fn_name in {"chat_respond", "ask_clarification", "request_confirmation"}:
        return {"sandy_face": "calm", "mood": "neutral",
                "persona_intensity": "standard"}
    return {"sandy_face": "idle", "mood": "neutral",
            "persona_intensity": "standard"}


def _fn_to_intent(name: str) -> str:
    """Map a tool name to an intent string the router/execute nodes expect."""
    _map = {
        "ask_clarification": "clarify.ask",
        "request_confirmation": "pending.confirm",
        "chat_respond": "chat.general",
        "chat_emotional": "chat.emotional_support",
        "pending_confirm": "pending.confirm",
        "pending_reject": "pending.reject",
        "pending_select": "pending.select_option",
        "task_list": "task.list",
    }
    if name in _map:
        return _map[name]
    # task_create → task.create  |  reminder_list → reminder.list
    return name.replace("_", ".", 1)


def _fn_to_routing_hint(name: str) -> str:
    if name == "ask_clarification":
        return "clarify"
    if name in {"request_confirmation", "pending_confirm", "pending_reject", "pending_select"}:
        return "pending_confirm"
    return "execute_direct"


def _build_user_prompt(state: SandyState) -> str:
    parts = [f"رسالة المستخدم: {state['message']}"]
    if state.get("conversation_history"):
        last = state["conversation_history"][-2:]
        history_text = "\n".join(
            f"{'المستخدم' if m['role'] == 'user' else 'Sandy'}: {m['content']}"
            for m in last
        )
        parts.append(f"\nآخر رسائل:\n{history_text}")
    if state.get("pending_state"):
        p = state["pending_state"]
        ctx = f"\nيوجد pending نشط: نوعه={p.get('type')} | action={p.get('action')}"
        if p.get("type") == "clarification":
            orig = (p.get("original_message") or "").strip()
            if orig:
                ctx += f"\nالرسالة الأصلية للمستخدم: '{orig}'"
        parts.append(ctx)
    return "\n".join(parts)


def route_with_fc(
    state: SandyState,
    declarations: List[Dict[str, Any]],
    agent_name: str = "specialist",
) -> SandyState:
    """Run one native function-calling pass and return state with function_call,
    intent, template, mood, face, and routing_hint. declarations is the tool
    catalog the model sees; agent_name feeds the Langfuse trace name and tags.
    """
    fc: Dict[str, Any] = dict(_FC_DEFAULT_CALL)
    fn_name = "chat_respond"
    intent = "chat.general"
    routing_hint = "execute_direct"
    requires_clarification = False
    clarification_q: Optional[str] = None
    multi_fcs: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None

    try:
        client = AzureIntentClient()

        # Stable prefix (cacheable): persona/rules + per-user address + the shared
        # disambiguation rules. Tools are passed separately and are equally stable.
        system = (
            _ROUTER_SYSTEM
            + "\n\n" + address_instruction()
            + "\n\n" + DISAMBIGUATION_RULES_AR
        )

        # Volatile suffix kept out of the cached prefix: the live device list goes
        # into the user turn so device_control only picks real, registered devices.
        user_prompt = _build_user_prompt(state)
        try:
            from app.agent.tools.schemas.device_tools import build_device_catalog

            device_catalog = build_device_catalog()
            if device_catalog:
                user_prompt += "\n\n" + device_catalog
        except Exception:  # noqa: BLE001 — never let device lookup break routing
            pass

        tools = _build_native_tools(declarations)

        _t = time.perf_counter()
        msg = client.complete_with_tools(system, user_prompt, tools)
        logger.info(f"[fc_router] routing: {(time.perf_counter()-_t)*1000:.0f}ms")

        calls = _parse_tool_message(msg)

        # Deterministic backstop: the model must never route to a tool that does
        # not exist. Validate every picked name against the live registry + the
        # routing-only meta-tools; drop unknowns. If nothing valid survives, chat.
        from app.agent.tools.registry import get_registry

        valid_names = set(get_registry().all_names()) | _META_TOOL_NAMES
        calls = [c for c in calls if c["name"] in valid_names]
        if not calls:
            calls = [dict(_FC_DEFAULT_CALL)]

        if len(calls) >= 2:
            multi_fcs = calls
        fc = calls[0]
        fn_name = fc["name"]

        intent = _fn_to_intent(fn_name)
        routing_hint = _fn_to_routing_hint(fn_name)
        requires_clarification = fn_name == "ask_clarification"
        clarification_q = fc["args"].get("question") if requires_clarification else None

        logger.debug(f"[fc_router] FC: {fn_name} → intent={intent}")
        if multi_fcs:
            logger.debug(f"[fc_router] multi-FC: {[f['name'] for f in multi_fcs]}")

    except Exception as exc:
        logger.error(f"[fc_router] routing failed: {exc}")
        error = f"route_with_fc failed: {exc}"

        # Try GPT routing before giving up to the safe default.
        try:
            from app.agent.model_fallback import route_with_gpt
            gpt_intent = route_with_gpt(state.get("message", ""))
            if gpt_intent and "task" in gpt_intent:
                intent = "task.create"
                routing_hint = "execute_direct"
                fn_name = "task_create"
                fc = {"name": "task_create", "args": {}}
            elif gpt_intent and gpt_intent == "reminder":
                intent = f"{gpt_intent}.create"
                routing_hint = "execute_direct"
                fn_name = "reminder_create"
                fc = {"name": "reminder_create", "args": {}}
        except Exception:
            pass

    face_mood = _derive_face_mood(fn_name)
    persona_intensity = face_mood["persona_intensity"]

    from app.agent.graph.response_templates import get_response_template
    template = get_response_template(intent, persona_intensity)

    return merge_state(state, {
        "intent": intent,
        "function_call": fc,
        "function_calls": multi_fcs or None,
        "confidence": 1.0 if fn_name not in {"chat_respond"} else 0.7,
        "complexity": None,
        "mood": face_mood["mood"],
        "sandy_face": face_mood["sandy_face"],
        "urgency": None,
        "requires_clarification": requires_clarification,
        "routing_hint": routing_hint,
        "clarification_question": clarification_q,
        "persona_intensity": persona_intensity,
        "persona_snippet": None,
        "response_template": template or None,
        "error": error,
    })
