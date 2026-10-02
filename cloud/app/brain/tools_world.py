"""Tools that act outside the blocks: devices, scenes, the web, the weather, images.

A device is actuated only after `command_payload` validates the action and
`send_to_topic` finds the topic in the caller's own registry; an unknown device
or action is refused with what is available, never guessed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.brain.ctx import TurnCtx
from app.brain.when import _chat_fn

logger = logging.getLogger(__name__)

SCENES_HINT = "ما عرفت هاد المشهد — جرّب: دراسة، قراءة، عصف ذهني، راحة، فيلم، نوم، صباح، إطفاء."


def _no(reply: str) -> Dict[str, Any]:
    """A refusal the user hears: the tool ran and the answer is no."""
    return {"ok": False, "reply": reply}


def _resolve_device(name: str) -> Optional[Dict[str, Any]]:
    """A registered device by its slug or (case-insensitive) label."""
    from app.features.device_store import get_device, list_devices

    name = (name or "").strip().lower()
    if not name:
        return None
    device = get_device(name)
    if device is not None:
        return device
    for pub in list_devices():
        if pub.get("label", "").strip().lower() == name:
            return get_device(pub["name"])
    return None


def _confirm_text(label: str, action: str, payload: str) -> str:
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


def device_control(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.device_store import command_payload, device_topic, list_devices, set_state
    from app.integrations.room_device import get_room_device_client

    device = _resolve_device(str(args.get("device", "")))
    if device is None:
        devices = list_devices()
        if not devices:
            return _no("ما في عندك أجهزة مضافة بعد — ضيفها من تبويب التحكّم بالتطبيق.")
        names = "، ".join(d["label"] for d in devices)
        return _no(f"ما لقيت جهاز بهالاسم. أجهزتك: {names}. أي واحد تقصد؟")

    label = device.get("label", device.get("name", ""))
    action = str(args.get("action", "")).strip()
    res = command_payload(device, action, args.get("value", ""))
    if not res.get("ok"):
        allowed = "، ".join(str(a) for a in res.get("allowed", [])) or "—"
        return _no(f"ما ينفع هالأمر لـ {label}. المتاح: {allowed}.")
    payload = res["payload"]
    topic = device_topic(device)
    if not topic:
        return _no(f"{label} مش مربوط بمخرج صحيح — راجع إعداده بالتطبيق.")
    try:
        sent = get_room_device_client().send_to_topic(topic, payload)
    except Exception:  # noqa: BLE001 — the broker boundary; reported as not sent
        logger.warning("[brain] device send failed", exc_info=True)
        sent = False
    if not sent:
        return _no(f"{_confirm_text(label, action, payload)} — بس {label} مش متّصل هلّق.")
    set_state(device["name"], payload)
    return {"ok": True, "reply": _confirm_text(label, action, payload)}


def scene_apply(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.scene_store import apply_scene

    # apply_scene sends each action once; it reports how many reached the room.
    r = apply_scene(str(args.get("name", "")))
    if not r.get("ok"):
        return _no(SCENES_HINT)
    suffix = " وأرسلتها للغرفة 🏠" if r.get("sent") else " (الغرفة مش متّصلة)"
    return {"ok": True, "reply": f"✨ جهّزت مشهد «{r['label']}»{suffix}."}


def room_restore(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.scene_store import restore_room

    r = restore_room()
    if not r.get("ok"):
        return _no("ما في مشهد طبّقته قبل هيك أرجّع عنه.")
    if not r.get("sent"):
        return _no("الغرفة مش متّصلة هلّق، ما قدرت أرجّعها.")
    return {"ok": True, "reply": "رجّعت الغرفة زي ما كانت 🏠"}


def web_search(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.research import web_answer

    query = str(args.get("query") or ctx.message or "").strip()
    return {"ok": True, "reply": web_answer(query, ctx.message, _chat_fn())}


def weather(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.weather import format_weather_for_prompt, get_weather, home_city

    city = str(args.get("city") or "").strip() or home_city(ctx.user_id)
    data = get_weather(city)
    if not data:
        return _no(f"ما قدرت أجيب بيانات الطقس لـ {city} حالياً.")
    return {"ok": True, "reply": format_weather_for_prompt(data)}


def image(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.vision import generate_image_with_azure

    prompt = str(args.get("prompt") or ctx.message or "").strip()
    image_bytes = generate_image_with_azure(prompt) if prompt else None
    if not image_bytes:
        return _no("ما قدرت أولد الصورة حاليًا. جرّب تغيّر الوصف شوي أو أعد المحاولة.")
    ctx.artifacts["image_bytes"] = image_bytes
    ctx.artifacts["caption"] = prompt
    return {"ok": True, "reply": "جهزت الصورة."}
