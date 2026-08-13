"""scenes tools."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def scene_apply(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.scene_store import apply_scene, get_scene

    name = str(args.get("name", ""))
    r = apply_scene(name)
    if not r.get("ok"):
        return {"handled": True, "reply": "ما عرفت هاد المشهد — جرّب: دراسة، قراءة، عصف ذهني، راحة، فيلم، نوم، صباح، إطفاء."}

    # فعّل المشهد فعليًا — للمالك فقط (غرفته الفيزيائية). كل فعل: لو جهازه مسجّل
    # بالسجلّ نمرّ بنفس المسار المحقَّق (device_topic + command_payload)؛ وإلا نرجع
    # للمسار القديم للروم-نود (انتقالي حتى تنتقل كل الأجهزة للسجلّ).
    sc = get_scene(name) or {}
    sent_to_room = actuate_scene_actions(sc.get("actions") or [])

    suffix = " وأرسلتها للغرفة 🏠" if sent_to_room else " (الغرفة مش متّصلة)"
    return {"handled": True, "reply": f"✨ جهّزت مشهد «{r['label']}»{suffix}."}


def actuate_scene_actions(actions: list) -> bool:
    """Apply a scene's actions to hardware. Registry devices go through the
    validated path; unknown names fall back to the legacy room-node vocab.
    Returns True if at least one action reached the broker.

    No owner check here any more. Scenes are a per-tenant feature, so gating the
    whole function on "are you the owner" meant nobody else's scene could ever
    move anything. Each path now carries its own, narrower gate: registry devices
    are checked against the calling tenant's own registry inside
    ``send_to_topic``, and the legacy fixed ``room/cmd/*`` vocab stays owner-only
    inside ``client.send`` because those topics carry no device identity.
    """
    try:
        from app.features.device_store import command_payload, device_topic, get_device
        from app.integrations.room_device import get_room_device_client

        client = get_room_device_client()
        sent_any = False
        for a in actions:
            dev_name = str(a.get("device", "")).strip().lower()
            value = str(a.get("value", "")).strip()
            if not dev_name or not value:
                continue
            device = get_device(dev_name)
            if device is not None:  # registry device — validated path
                res = command_payload(device, value)
                topic = device_topic(device)
                if res.get("ok") and topic and client.send_to_topic(topic, res["payload"]):
                    sent_any = True
            elif client.send(dev_name, value):  # legacy room-vocab fallback
                sent_any = True
        return sent_any
    except Exception:  # noqa: BLE001 — actuation must never crash the turn
        return False


def scene_list(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.scene_store import list_scenes

    scenes = list_scenes()
    if not scenes:
        return {"handled": True, "reply": "ما في مشاهد بعد."}
    lines = [f"{s['icon']} {s['label']}" for s in scenes]
    return {"handled": True, "reply": "مشاهد الغرفة:\n" + "  ·  ".join(lines)}
