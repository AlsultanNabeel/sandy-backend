"""Tools that act outside the blocks: devices, scenes, the web, the weather, images.

A device is actuated only after `command_payload` validates the action and
`send_to_topic` finds the topic in the caller's own registry; an unknown device
or action is refused with what is available, never guessed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.brain import when as W
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


def offline_line(label: str) -> str:
    """A device whose board is gone: not «it did not work», which reads as a fault to retry."""
    return f"{label} مش متّصل هلّق، فما بعتّله الأمر. تأكّد إنه شغّال وعلى الشبكة."


# «شوي» on a dimmer: a fifth of its range.
STEP = 20


def _targets(args: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(devices, names not found) for one `device`, a list of `devices`, or a `room`."""
    from app.features.device_store import get_device, list_devices

    if args.get("room"):
        room = str(args["room"]).strip().lower()
        hits = [get_device(d["name"]) for d in list_devices()
                if str(d.get("room") or "").strip().lower() == room]
        return [d for d in hits if d], ([] if hits else [str(args["room"])])
    names = args.get("devices") if isinstance(args.get("devices"), list) else [args.get("device", "")]
    found, missing = [], []
    for n in names:
        d = _resolve_device(str(n or ""))
        (found.append(d) if d else missing.append(str(n or "")))
    return found, missing


def _relative(device: Dict[str, Any], by: Any) -> Optional[str]:
    """A dimmer's level moved by ``by`` from where it is («خفّفي شوي» = -STEP)."""
    try:
        step = int(by)
    except (TypeError, ValueError):
        return None
    meta = device.get("meta") or {}
    lo, hi = int(meta.get("min", 0) or 0), int(meta.get("max", 100) or 100)
    state = str(device.get("state") or "").strip().lower()
    now = int(state) if state.isdigit() else (hi if state == "on" else lo)
    return str(max(lo, min(hi, now + step)))


def _actuate_one(device: Dict[str, Any], action: str, value: Any) -> Tuple[bool, str]:
    """(it happened, what to say). Not sent means not done, and the reply says so."""
    from app.features.device_store import command_payload, device_topic, set_state
    from app.integrations.room_device import get_room_device_client

    label = device.get("label", device.get("name", ""))
    res = command_payload(device, action, value)
    if not res.get("ok"):
        allowed = "، ".join(str(a) for a in res.get("allowed", [])) or "—"
        return False, f"ما ينفع هالأمر لـ {label}. المتاح: {allowed}."
    payload = res["payload"]
    topic = device_topic(device)
    if not topic:
        return False, f"{label} مربوط بطريقة ما عادت مدعومة، فما بقدر أوصله. احذفه من التحكّم بالتطبيق."
    if device.get("board_gone"):
        # Its board said it went: the broker would take the command and drop it.
        return False, offline_line(label)
    try:
        sent = get_room_device_client().send_to_topic(topic, payload)
    except Exception:  # noqa: BLE001 — the broker boundary; reported as not sent
        logger.warning("[brain] device send failed", exc_info=True)
        sent = False
    if not sent:
        return False, f"ما اشتغل: ما قدرت أوصّل الأمر لـ {label}. جرّب كمان شوي."
    set_state(device["name"], payload)
    return True, _confirm_text(label, action, payload)


def device_control(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """One device, several («طفّي كل الأضواء»), or a room; `by` moves a dimmer
    relative to where it is («خفّفي الإضاءة شوي»)."""
    from app.features.device_store import list_devices

    devices, missing = _targets(args)
    if not devices:
        known = list_devices()
        if not known:
            return _no("ما في عندك أجهزة مضافة بعد — ضيفها من تبويب التحكّم بالتطبيق.")
        names = "، ".join(d["label"] for d in known)
        return _no(f"ما لقيت جهاز بهالاسم. أجهزتك: {names}. أي واحد تقصد؟")
    action = str(args.get("action", "")).strip()
    done, lines = 0, []
    for d in devices:
        value: Any = args.get("value", "")
        act = action
        if args.get("by") not in (None, ""):
            value = _relative(d, args["by"])
            act = "set"
            if value is None:
                lines.append(f"ما فهمت قديش أغيّر {d.get('label', '')}.")
                continue
        ok, line = _actuate_one(d, act, value)
        done += ok
        lines.append(line)
    lines += [f"ما لقيت «{m}»." for m in missing]
    return {"ok": done == len(devices) and not missing, "done": done,
            "reply": "\n".join(lines)}


def device_state(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """«الضو شغّال؟»: each device's last state, whether it is connected, when last heard."""
    from app.features.device_store import get_device, list_devices

    if args.get("device") or args.get("room") or args.get("devices"):
        devices, missing = _targets(args)
        if not devices:
            return _no(f"ما لقيت «{'، '.join(missing)}».")
    else:
        devices = [get_device(d["name"]) for d in list_devices()]
    rows = [{"device": d.get("label") or d.get("name"), "name": d.get("name"),
             "room": d.get("room") or "", "state": d.get("state") or "غير معروف",
             "connected": bool(d.get("online")),
             "last_seen": W.local_text(d["last_seen"]) if d.get("last_seen") else ""}
            for d in devices if d]
    return {"ok": True, "devices": rows,
            "note": "state هي آخر حالة انبعتت للجهاز؛ connected إذا هو متّصل هلأ."}


def scene_apply(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.scene_store import apply_scene

    # apply_scene sends each action once; it reports how many reached the room.
    r = apply_scene(str(args.get("name", "")))
    if not r.get("ok"):
        return _no(SCENES_HINT)
    tail = _passed_over(r)
    if not r.get("sent"):
        return _no(f"ما تطبّق مشهد «{r['label']}»، ما وصل ولا جهاز.{tail}")
    return {"ok": not tail, "reply": f"✨ طبّقت مشهد «{r['label']}»{'.' + tail if tail else ' 🏠'}"}


def _passed_over(r: Dict[str, Any]) -> str:
    """What a scene or a restore left out, by name: the devices whose board is gone, the
    room words no device of his answers to, and the ones the command did not reach."""
    parts = []
    if r.get("skipped"):
        parts.append(f" ما عندك {'، '.join(r['skipped'])}، فتخطّيتها.")
    if r.get("offline"):
        parts.append(f" {'، '.join(r['offline'])} مش متّصل هلّق، فتخطّيته.")
    if r.get("missed"):
        parts.append(f" وما وصل لـ: {'، '.join(r['missed'])}.")
    return "".join(parts)


def room_restore(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.scene_store import restore_room

    r = restore_room()
    if not r.get("ok"):
        return _no("ما في مشهد طبّقته قبل هيك أرجّع عنه.")
    tail = _passed_over(r)
    if not r.get("sent"):
        return _no(f"ما قدرت أرجّع الغرفة، ما وصل ولا جهاز.{tail}")
    return {"ok": not tail, "reply": f"رجّعت الغرفة زي ما كانت{'.' + tail if tail else ' 🏠'}"}


def web_search(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.research import web_answer

    query = str(args.get("query") or ctx.message or "").strip()
    return {"ok": True, "reply": web_answer(query, ctx.message, _chat_fn())}


def weather(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    from app.features.weather import format_weather_for_prompt, get_weather, home_city

    city = str(args.get("city") or "").strip() or home_city(ctx.user_id)
    if not city:
        return _no("ما بعرف وين ساكن. بأي مدينة بدك الطقس؟")
    data = get_weather(city)
    if not data:
        return _no(f"ما قدرت أجيب بيانات الطقس لـ {city} حالياً.")
    return {"ok": True, "reply": format_weather_for_prompt(data)}


def image(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """One image a turn: each is a paid call, and the reply carries only one."""
    from app.features.vision import generate_image_with_azure

    if ctx.artifacts.get("image_bytes"):
        return _no("برسم صورة وحدة بكل مرة. هي الأولى جاهزة، اطلب التانية بعدها.")
    prompt = str(args.get("prompt") or ctx.message or "").strip()
    image_bytes = generate_image_with_azure(prompt) if prompt else None
    if not image_bytes:
        return _no("ما قدرت أولد الصورة حاليًا. جرّب تغيّر الوصف شوي أو أعد المحاولة.")
    ctx.artifacts["image_bytes"] = image_bytes
    ctx.artifacts["caption"] = prompt
    return {"ok": True, "reply": "جهزت الصورة."}
