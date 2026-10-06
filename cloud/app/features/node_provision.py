"""Turn a node's declared outputs (from its heartbeat) into devices its owner can use.

PART_CATALOGUE is presentation only: nothing appears for an output the board
didn't declare. Provisioning is additive and never touches labels or rooms the
owner set; control types and enum values follow the firmware.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# The display's 25 expressions, in firmware MOOD_MAP order (brain-core/main/sandy_mqtt.c).
ROBOT_MOODS = [
    "idle", "happy", "curious", "sad", "alert", "surprised", "big_happy",
    "focused", "bored", "excited", "love", "angry", "confused", "thinking",
    "sleepy", "shy", "proud", "worried", "playful", "calm", "grumpy",
    "hopeful", "grateful", "disappointed", "silly",
]

ROBOT_MELODIES = [
    "boot", "happy", "curious", "sad", "alert", "error",
    "focus_start", "focus_break", "focus_end",
    "hello", "bye", "yes", "no", "thinking", "celebrate", "notify", "lowbatt",
]

ROBOT_GESTURES = [
    "nod", "shake", "tilt", "scan", "dance",
    "wake", "sleep", "look_left", "look_right", "center",
]

# أول أربعة مؤشّر خصوصية (الأبيض = الصوت طالع من الغرفة)؛ اللوح بيرفض المؤثرات وقت الجلسة الحيّة.
ROBOT_LED = [
    "off", "idle", "listening", "talking",
    "rainbow", "breathe", "pulse", "blink", "fire",
    "police", "party", "sunrise", "ocean", "candle", "solid",
]

# بنفس أسماء الفيرموير حرفيًا (kFrameSizes بـ cam_control).
CAM_FRAME_SIZES = [
    "96X96", "QQVGA", "QCIF", "HQVGA", "240X240", "QVGA", "CIF",
    "HVGA", "VGA", "SVGA", "XGA", "HD", "SXGA", "UXGA",
]

# output id -> how to present it. `name` is the device slug, unique per tenant.
PART_CATALOGUE: Dict[str, Dict[str, Any]] = {
    "mood": {
        "name": "sandy_face", "label": "وش ساندي", "control_type": "enum",
        "meta": {"values": ROBOT_MOODS},
    },
    "gesture": {
        "name": "sandy_gesture", "label": "حركات ساندي", "control_type": "enum",
        # `momentary`: the values that are one-shot commands, drawn as buttons (a picker
        # sends only when its value changes, so the same one twice was nothing).
        "meta": {"values": ROBOT_GESTURES, "momentary": ROBOT_GESTURES},
    },
    "servo": {
        "name": "sandy_head", "label": "رقبة ساندي", "control_type": "dimmer",
        # Degrees: 90 is centre.
        "meta": {"min": 0, "max": 180},
    },
    "led": {
        "name": "sandy_led", "label": "إضاءة ساندي", "control_type": "enum",
        "meta": {"values": ROBOT_LED},
    },
    "screen_size": {
        "name": "sandy_screen_size", "label": "حجم الكتابة",
        "control_type": "enum",
        "meta": {"values": ["small", "medium", "large"]},
    },
    "screen": {
        "name": "sandy_screen", "label": "شاشة ساندي", "control_type": "text",
        # نص حر؛ القيمة `dismiss` بتشيله وبترجّع الوش.
        "meta": {"placeholder": "اكتب اللي بدك يظهر ع وشها", "max_bytes": 255},
    },
    "buzzer": {
        "name": "sandy_buzzer", "label": "جرس ساندي", "control_type": "enum",
        "meta": {"values": ROBOT_MELODIES, "momentary": ROBOT_MELODIES},
    },
    "mic_l": {
        "name": "sandy_mic_left", "label": "المايك الشمال", "control_type": "switch",
    },
    "mic_r": {
        "name": "sandy_mic_right", "label": "المايك اليمين", "control_type": "switch",
    },
    "mic_l_gain": {
        "name": "sandy_mic_left_gain", "label": "مكسب المايك الشمال",
        "control_type": "dimmer",
        # 100 is unity; the firmware also clamps at 300.
        "meta": {"min": 0, "max": 300},
    },
    "mic_r_gain": {
        "name": "sandy_mic_right_gain", "label": "مكسب المايك اليمين",
        "control_type": "dimmer", "meta": {"min": 0, "max": 300},
    },
    "volume": {
        "name": "sandy_volume", "label": "صوت ساندي", "control_type": "dimmer",
        "meta": {"min": 0, "max": 100},
    },
    "speaker_test": {
        "name": "sandy_speaker_test", "label": "أصوات السماعة", "control_type": "enum",
        "meta": {"values": ["beep", "chime", "alert", "sweep", "soft", "happy"],
                 "momentary": ["beep", "chime", "alert", "sweep", "soft", "happy"]},
    },

    # ── الكاميرا: بادئة `cam/` لأنها بتشارك معرّف الوحدة مع الدماغ ─────────────
    "cam/flash": {
        "name": "cam_flash", "label": "فلاش الكاميرا", "control_type": "switch",
    },
    "cam/flash_level": {
        "name": "cam_flash_level", "label": "قوة الفلاش", "control_type": "dimmer",
        # القيمة الخام اللي الفيرموير بيكتبها ع الطرف.
        "meta": {"min": 0, "max": 255},
    },
    "cam/flash_mode": {
        "name": "cam_flash_mode", "label": "وضع الفلاش", "control_type": "enum",
        "meta": {"values": ["off", "on", "auto"]},
    },
    "cam/snapshot": {
        "name": "cam_snapshot", "label": "التقاط صورة", "control_type": "enum",
        "meta": {"values": ["take"], "momentary": ["take"]},
    },
    "cam/stream": {
        "name": "cam_stream", "label": "بث مباشر", "control_type": "switch",
    },
    "cam/framesize": {
        "name": "cam_framesize", "label": "دقة الصورة", "control_type": "enum",
        "meta": {"values": CAM_FRAME_SIZES},
    },
    "ir": {
        "name": "sandy_ir", "label": "ريموت ساندي", "control_type": "ir",
        # بلا `meta` بالقصد: الأزرار بيتعلّمها المالك، وميتا الكتالوج بتندمج بكل
        # نبضة، فحتى `{"buttons": {}}` كانت رح تدهس أزراره.
    },

    # ── عقدة الغرفة: بادئة `room/` لنفس السبب ────────────────────────────────
    "room/light": {
        "name": "room_light", "label": "ضوء الغرفة", "control_type": "switch",
        # مفتاح مش تعتيم: السيرفو بيكبس القلّاب ميكانيكيًا.
    },
    "room/music": {
        "name": "room_music", "label": "موسيقى الغرفة", "control_type": "enum",
        # قيم handleMusic بـ room-node.ino؛ `play` بدها مجلد ومقطع فمش من القائمة.
        "meta": {"values": ["stop", "pause", "resume", "next", "prev"],
                 "momentary": ["next", "prev"]},
    },

    "cam/quality": {
        "name": "cam_quality", "label": "وضوح الصورة", "control_type": "enum",
        # المستشعر من 10 لـ 63 والأصغر أوضح، فبنعرض أسماء واللوح بيترجمها.
        "meta": {"values": ["high", "medium", "low"]},
    },
}

ROBOT_ROOM = "ساندي"


def provision_from_outputs(node_id: str, outputs: List[Dict[str, Any]],
                           label: str = "") -> Dict[str, Any]:
    """Register a device for each catalogued output this node reports.

    Runs inside the owner's tenant; returns a summary rather than raising (heartbeat path).
    """
    from app.features.device_store import add_device, get_devices

    node_id = (node_id or "").strip()
    if not node_id or not isinstance(outputs, list):
        return {"ok": False, "error": "bad_input"}

    # One read for all outputs: this runs on every heartbeat.
    existing_by_name = get_devices([
        PART_CATALOGUE[str(o.get("id", "")).strip()]["name"]
        for o in outputs
        if isinstance(o, dict) and str(o.get("id", "")).strip() in PART_CATALOGUE
    ])

    added: List[str] = []
    refreshed: List[str] = []
    skipped: List[str] = []

    for out in outputs:
        if not isinstance(out, dict):
            continue
        oid = str(out.get("id", "")).strip()
        spec = PART_CATALOGUE.get(oid)
        if spec is None:
            # Newer firmware may declare parts we don't know yet; ignore them.
            skipped.append(oid)
            continue

        name = spec["name"]
        existing = existing_by_name.get(name)
        if existing is not None:
            if _refresh_from_catalogue(name, existing, spec):
                refreshed.append(name)
            continue   # already provisioned; the owner keeps their label and room

        res = add_device(
            name=name,
            label=spec["label"],
            control_type=spec["control_type"],
            transport={"kind": "node", "node_id": node_id, "output": oid},
            room=(label or ROBOT_ROOM),
            meta=spec.get("meta", {}),
        )
        if res.get("ok"):
            added.append(name)
        else:
            if res.get("error") != "exists":
                logger.warning("[provision] %s failed: %s", name, res.get("error"))

    if added:
        logger.info("[provision] node %s: added %s", node_id, ", ".join(added))
    if refreshed:
        logger.info("[provision] node %s: refreshed %s", node_id, ", ".join(refreshed))
    return {"ok": True, "added": added, "refreshed": refreshed,
            "unknown_outputs": skipped}


def _refresh_from_catalogue(name: str, existing: Dict[str, Any],
                        spec: Dict[str, Any]) -> bool:
    """Bring an existing device's control type and catalogue meta in line; owner's label/room untouched.

    Writes only real differences (heartbeats arrive every few seconds).
    """
    from app.features.device_store import update_device

    patch: Dict[str, Any] = {}

    want_type = spec.get("control_type")
    if want_type and existing.get("control_type") != want_type:
        patch["control_type"] = want_type

    # Merged, not replaced: other meta keys are the owner's.
    catalogue_meta = spec.get("meta") or {}
    if catalogue_meta:
        current = existing.get("meta") or {}
        if not isinstance(current, dict):
            current = {}
        if not all(current.get(k) == v for k, v in catalogue_meta.items()):
            patch["meta"] = {**current, **catalogue_meta}

    if not patch:
        return False

    res = update_device(name, **patch)
    if not res.get("ok"):
        logger.warning("[provision] refresh %s failed: %s", name, res.get("error"))
        return False
    logger.info("[provision] %s brought in line with the catalogue: %s",
                name, ", ".join(sorted(patch)))
    return True


def board_states(telemetry: Dict[str, Any]) -> Dict[str, str]:
    """The brain's heartbeat read as its outputs' states: the volume and the mics' gain as
    levels, a mic as on unless muted. Only what the heartbeat carries."""
    tel = telemetry if isinstance(telemetry, dict) else {}
    states: Dict[str, str] = {}
    for key in ("volume", "mic_l_gain", "mic_r_gain"):
        if isinstance(tel.get(key), int) and not isinstance(tel.get(key), bool):
            states[key] = str(tel[key])
    for mic in ("mic_l", "mic_r"):
        if isinstance(tel.get(f"{mic}_muted"), bool):
            states[mic] = "off" if tel[f"{mic}_muted"] else "on"
    return states


def states_for_owner(node_id: str, owner_id: str, telemetry: Dict[str, Any]) -> int:
    """`board_states` written on the node owner's devices, from the tenant-less heartbeat
    thread (the owner comes from the node document, as for provisioning)."""
    from app.features.device_store import set_board_states
    from app.utils.user_profiles import active_user_profile_context

    states = board_states(telemetry)
    if not owner_id or not states:
        return 0
    with active_user_profile_context(
        {"chat_id": owner_id, "permissions": "all", "relation": "user"}
    ):
        return set_board_states(node_id, states)


def provision_for_owner(node_id: str, owner_id: str,
                        outputs: List[Dict[str, Any]],
                        label: str = "") -> Dict[str, Any]:
    """Provision in the node owner's tenant, from the tenant-less heartbeat thread.

    The owner comes from the node document, so a heartbeat can't nominate its own owner.
    """
    from app.utils.user_profiles import active_user_profile_context

    if not owner_id:
        return {"ok": False, "error": "no_owner"}
    with active_user_profile_context(
        {"chat_id": owner_id, "permissions": "all", "relation": "user"}
    ):
        return provision_from_outputs(node_id, outputs, label)
