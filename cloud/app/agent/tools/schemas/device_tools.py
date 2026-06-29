"""Device control — the one generic FC tool for real-world devices.

Kept in its own file (not mixed into life_tools) so the device system is a clean,
separable module. The brain may only act on a **registered** device with a
**validated** action; an unknown device or action is **refused** with the list of
valid options so Sandy asks — it never guesses or applies the "closest" thing.
This is what ends the "turn the light on -> applied the off scene" hallucination.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def _resolve_device(name: str) -> Optional[Dict[str, Any]]:
    """Find a registered device by its slug name or (case-insensitive) label."""
    from app.features.device_store import get_device, list_devices

    name = (name or "").strip().lower()
    if not name:
        return None
    d = get_device(name)
    if d is not None:
        return d
    for pub in list_devices():
        if pub.get("label", "").strip().lower() == name:
            return get_device(pub["name"])
    return None


def _device_topic(device: Dict[str, Any]) -> Optional[str]:
    """The MQTT topic to actuate this device, derived from its transport."""
    t = device.get("transport") or {}
    kind = str(t.get("kind", "")).strip().lower()
    if kind == "mqtt":
        return str(t.get("topic", "")).strip() or None
    if kind == "node":
        node_id = str(t.get("node_id", "")).strip()
        output = str(t.get("output", "")).strip()
        if node_id and output:
            return f"sandy/node/{node_id}/{output}"
    return None


def _confirm_text(label: str, action: str, payload: str) -> str:
    """Sandy's natural confirmation for a successful command."""
    a = (action or "").strip().lower()
    p = (payload or "").strip().lower()
    if a == "on" or p == "on":
        return f"شغّلت {label} ✨"
    if a == "off" or p == "off":
        return f"طفّيت {label}"
    if p == "open":
        return f"فتحت {label}"
    if p == "close":
        return f"سكّرت {label}"
    if p.isdigit():
        return f"ضبطت {label} على {p}"
    return f"ضبطت {label}: {payload}"


def device_control(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.device_store import command_payload, list_devices, set_state

    raw_name = str(args.get("device", "")).strip()
    device = _resolve_device(raw_name)

    # Unknown device -> refuse and list what's available. Never guess.
    if device is None:
        devices = list_devices()
        if not devices:
            return {"handled": True,
                    "reply": "ما في عندك أجهزة مضافة بعد — ضيفها من تبويب التحكّم بالتطبيق."}
        names = "، ".join(d["label"] for d in devices)
        return {"handled": True,
                "reply": f"ما لقيت جهاز بهالاسم. أجهزتك: {names}. أي واحد تقصد؟"}

    label = device.get("label", device.get("name", ""))
    action = str(args.get("action", "")).strip()
    value = args.get("value", "")

    res = command_payload(device, action, value)
    if not res.get("ok"):
        allowed = "، ".join(str(a) for a in res.get("allowed", [])) or "—"
        return {"handled": True,
                "reply": f"ما ينفع هالأمر لـ {label}. المتاح: {allowed}."}

    payload = res["payload"]
    topic = _device_topic(device)
    if not topic:
        return {"handled": True,
                "reply": f"{label} مش مربوط بمخرج صحيح — راجع إعداده بالتطبيق."}

    # Actuate via the registry-driven topic (owner-gated inside the client).
    sent = False
    try:
        from app.integrations.room_device import get_room_device_client

        sent = get_room_device_client().send_to_topic(topic, payload)
    except Exception:  # noqa: BLE001 — actuation must never crash the turn
        sent = False

    if sent:
        set_state(device["name"], payload)
        return {"handled": True, "reply": _confirm_text(label, action, payload)}
    return {"handled": True,
            "reply": f"{_confirm_text(label, action, payload)} — بس {label} مش متّصل هلّق."}


def device_list(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.device_store import list_devices

    devices = list_devices()
    if not devices:
        return {"handled": True, "reply": "ما في أجهزة مضافة بعد."}
    lines = [f"• {d['label']}" + (f" ({d['room']})" if d.get("room") else "")
             for d in devices]
    return {"handled": True, "reply": "أجهزتك:\n" + "\n".join(lines)}


def build_device_catalog() -> str:
    """One-line-per-device list to inject into the FC prompt, so the model can only
    pick a real device + its real actions (no inventing names/values)."""
    from app.features.device_store import list_devices

    devices = list_devices()
    if not devices:
        return ""
    lines: List[str] = []
    for d in devices:
        ctype = d.get("control_type", "")
        meta = d.get("meta") or {}
        if ctype in ("switch", "dimmer"):
            acts = "on|off" + ("|0..100" if ctype == "dimmer" else "")
        elif ctype == "cover":
            acts = "open|close|stop"
        elif ctype == "media":
            acts = "on|off|pause"
        elif ctype == "enum":
            acts = "|".join(str(v) for v in (meta.get("values") or []))
        elif ctype == "ir":
            acts = "|".join(sorted((meta.get("buttons") or {}).keys())) or "(no buttons yet)"
        else:
            acts = ctype
        lines.append(f"- {d['label']} (device={d['name']}) → {acts}")
    return "الأجهزة المسجّلة (device_control فقط على هذول):\n" + "\n".join(lines)


DEVICE_TOOLS = [
    {
        "name": "device_control",
        "description": (
            "تحكّم بجهاز واقعي مسجّل (ضو/مروحة/ستارة/مكيف/سيرفو...). "
            "«ضوّي/نوري» = on، «طفّي» = off، «افتح/سكّر» للستارة. "
            "device لازم يكون من الأجهزة المسجّلة المعطاة بالبرومبت — ممنوع تخترع اسم. "
            "إذا ما في جهاز مطابق، الأداة بترجّع القائمة وتسأل."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "اسم الجهاز المسجّل (slug أو label)"},
                "action": {"type": "string", "description": "on|off|open|close|pause|set أو قيمة enum/IR"},
                "value": {"type": "string", "description": "قيمة اختيارية (نسبة، لون، اسم زر IR)"},
            },
            "required": ["device", "action"],
        },
        "handler": device_control,
    },
    {
        "name": "device_list",
        "description": "اعرض الأجهزة الواقعية المسجّلة عند المستخدم",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": device_list,
    },
]
