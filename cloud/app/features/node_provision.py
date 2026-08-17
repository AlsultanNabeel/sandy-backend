"""Turn a node's declared outputs into devices its owner can actually use.

The problem this solves: someone buys the robot, pairs it, opens the Control tab
and finds an empty list plus an "add device" form — for hardware that came in the
box. Her face, her neck and her microphones are not accessories the customer
should have to describe to the app.

The tempting fix is to seed a fixed list of parts at boot, which would be wrong
twice: it hardcodes an assumption that every board has a servo, and it breaks the
registry's own rule that devices are data rather than code.

So the hardware declares itself. The firmware publishes its outputs in every
heartbeat (``sandy/node/<id>/status``), and this module maps each declared output
onto a device row. Nothing appears for an output the board did not report — a
unit shipped without a neck simply has no neck in the app, with no code change.

The table below is therefore **not** a list of what exists. It is a presentation
catalogue: given that a board reports output ``servo``, this is the label, the
control type and the range to show. Adding a part to the robot means teaching the
firmware to declare it and adding one row here.

Provisioning is idempotent and additive: it never renames, reconfigures or
deletes a device the owner has since customised, and re-running it after a
firmware upgrade only fills in outputs that are new.

With one deliberate exception, which cost an evening to find: the **vocabulary**
of an enum is refreshed. A device's list of accepted values is not a preference
the owner set, it is the set of things the firmware will answer to — and once a
device row was created, the original code never touched it again. So a board
upgraded from one speaker sound to six kept offering the single sound it was
provisioned with, and the five new ones existed on the robot with no way to reach
them. The upgrade looked like it had failed. Labels, rooms and control types stay
the owner's; the value list follows the firmware.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# The 25 expressions the display can render, in the order the firmware's MOOD_MAP
# declares them. Kept in sync by hand with brain-core/main/sandy_mqtt.c — the
# device refuses an unknown value, so a drift here shows up as "that mood does
# nothing" rather than as anything dangerous.
ROBOT_MOODS = [
    "idle", "happy", "curious", "sad", "alert", "surprised", "big_happy",
    "focused", "bored", "excited", "love", "angry", "confused", "thinking",
    "sleepy", "shy", "proud", "worried", "playful", "calm", "grumpy",
    "hopeful", "grateful", "disappointed", "silly",
]

ROBOT_MELODIES = [
    "boot", "happy", "curious", "sad", "alert", "error",
    "focus_start", "focus_break", "focus_end",
    # نغمات التفاعل. الجرس بيزو سلبي بيعزف أي تردد، فكل وحدة قائمة نوتات
    # مش صوت مسجّل — يعني إضافة نغمة بتكلّف سطر مش ملف.
    "hello", "bye", "yes", "no", "thinking", "celebrate", "notify", "lowbatt",
]

# حركات الرقبة. رقبة بتروح لزاوية بس هي «مُموضِع»؛ رقبة بتومي وتهزّ وتترنّح
# بتصير وش إله جسم — والفرق تلاتين سطر لأن التنعيم موجود أصلًا.
ROBOT_GESTURES = [
    "nod", "shake", "tilt", "scan", "dance",
    "wake", "sleep", "look_left", "look_right", "center",
]

# مهرجانات الإضاءة. أول أربعة هنّ مؤشّر الخصوصية — الأبيض معناه الصوت طالع من
# الغرفة، وهاد مش زينة. الباقي مؤثرات، واللوح بيرفضها وقت الجلسة الحيّة عشان
# ما إشي يلوّن فوق المؤشّر (sandy_led.h).
ROBOT_LED = [
    "off", "idle", "listening", "talking",
    "rainbow", "breathe", "pulse", "blink", "fire",
    "police", "party", "sunrise", "ocean", "candle", "solid",
]

# أحجام صورة الكاميرا، بنفس أسماء الفيرموير حرفيًا (kFrameSizes بـ cam_control).
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
        "meta": {"values": ROBOT_GESTURES},
    },
    "servo": {
        "name": "sandy_head", "label": "رقبة ساندي", "control_type": "dimmer",
        # Degrees, not percent: 90 is centre, and a slider labelled 0-100 would
        # make "look straight ahead" an arbitrary number.
        "meta": {"min": 0, "max": 180},
    },
    "led": {
        "name": "sandy_led", "label": "إضاءة ساندي", "control_type": "enum",
        "meta": {"values": ROBOT_LED},
    },
    "screen_size": {
        "name": "sandy_screen_size", "label": "حجم الكتابة",
        "control_type": "enum",
        # ثلاث مقاسات، وكلها خطوط حقيقية موجودة باللوح. مقاس بيغيّر الرقم وما
        # بيغيّر الحروف أسوأ من غياب الخيار — بيبيّن إنه اشتغل.
        "meta": {"values": ["small", "medium", "large"]},
    },
    "screen": {
        "name": "sandy_screen", "label": "شاشة ساندي", "control_type": "text",
        # نص حر مش قائمة: اللي بينكتب ع وشها بيكتبه المالك ساعتها. القيمة
        # `dismiss` بتشيله وبترجّع الوش.
        "meta": {"placeholder": "اكتب اللي بدك يظهر ع وشها", "max_bytes": 255},
    },
    "buzzer": {
        "name": "sandy_buzzer", "label": "جرس ساندي", "control_type": "enum",
        "meta": {"values": ROBOT_MELODIES},
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
        # 100 is unity, above it amplifies the room's noise along with the voice.
        # The firmware clamps at 300 too; both ends agree on purpose.
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
        # مش بيب واحد. الجرس بيزو صغير وصوته زي اللعبة؛ هاد المكبّر الحقيقي،
        # فبيقدر يعمل تدرّج ترددي ونغمة ناعمة تنفع بالليل. والمسح الترددي
        # بيفحص المدى كله — سماعة بمشغّل ميت بتنجح بنغمة وحدة وبتفشل بالمسح.
        "meta": {"values": ["beep", "chime", "alert", "sweep", "soft", "happy"]},
    },
    "noise": {
        "name": "sandy_noise", "label": "عزل الضجّة", "control_type": "enum",
        "meta": {"values": ["off", "mild", "medium", "aggressive"]},
    },

    # ── الكاميرا ─────────────────────────────────────────────────────────────
    #
    # المفاتيح ببادئة `cam/` لأن الكاميرا **بتشارك نفس معرّف الوحدة** مع الدماغ
    # — هي جزء من ساندي مش صندوق تاني. بلا البادئة، `flash` بيقعد جنب `servo`
    # بقائمة وحدة، وأول ما حدا يضيف فلاش للدماغ بيصير تصادم صامت.
    #
    # والبادئة بتوصل الموضوع لحالها: device_topic بيركّب
    # `sandy/node/<id>/<المخرج>`، فـ `cam/flash` بيطلع
    # `sandy/node/<id>/cam/flash` — وهاد بالضبط وين الكاميرا بتسمع.
    "cam/flash": {
        "name": "cam_flash", "label": "فلاش الكاميرا", "control_type": "switch",
    },
    "cam/flash_level": {
        "name": "cam_flash_level", "label": "قوة الفلاش", "control_type": "dimmer",
        # صفر لـ ٢٥٥ مش مئوية: هاي القيمة اللي الفيرموير بيكتبها ع الطرف مباشرة،
        # وتحويلها لنسبة بيخلي «نص القوة» رقم اعتباطي.
        "meta": {"min": 0, "max": 255},
    },
    "cam/flash_mode": {
        "name": "cam_flash_mode", "label": "وضع الفلاش", "control_type": "enum",
        "meta": {"values": ["off", "on", "auto"]},
    },
    "cam/snapshot": {
        "name": "cam_snapshot", "label": "التقاط صورة", "control_type": "enum",
        "meta": {"values": ["take"]},
    },
    "cam/stream": {
        "name": "cam_stream", "label": "بث مباشر", "control_type": "switch",
    },
    "cam/framesize": {
        "name": "cam_framesize", "label": "دقة الصورة", "control_type": "enum",
        "meta": {"values": CAM_FRAME_SIZES},
    },
}

ROBOT_ROOM = "ساندي"


def provision_from_outputs(node_id: str, outputs: List[Dict[str, Any]],
                           label: str = "") -> Dict[str, Any]:
    """Register a device for each catalogued output this node reports.

    Must be called inside the owning tenant's context — device_store writes
    through the scoped collection, so with no active tenant every add is a no-op
    that returns "no_store" and nothing is created.

    Returns a summary rather than raising: this runs from a heartbeat, and a
    malformed payload must never take the ingest loop down with it.
    """
    from app.features.device_store import add_device, get_device

    node_id = (node_id or "").strip()
    if not node_id or not isinstance(outputs, list):
        return {"ok": False, "error": "bad_input"}

    added: List[str] = []
    refreshed: List[str] = []
    skipped: List[str] = []

    for out in outputs:
        if not isinstance(out, dict):
            continue
        oid = str(out.get("id", "")).strip()
        spec = PART_CATALOGUE.get(oid)
        if spec is None:
            # An output we have no presentation for. Not an error — a newer
            # firmware may declare parts this backend has not learned yet, and
            # the right response is to ignore it, not to guess a control type.
            skipped.append(oid)
            continue

        name = spec["name"]
        existing = get_device(name)
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
            # "exists" is benign; anything else is worth seeing once.
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
    """Bring an existing device in line with the catalogue.

    **Control type is a fact about the hardware, not a user preference, and it
    has to be allowed to change.** This function used to refresh only `meta`,
    which meant a part provisioned once kept its original widget for ever. The
    display was created as an on/off switch before it could take text; the
    catalogue was later corrected to `text`, and the device stayed a switch —
    because it already existed, so provisioning skipped it. The owner typed
    nothing, saw a toggle, flipped it, and watched it flip back. Three separate
    "the text field never appeared" reports were all this one line.

    A widget that does not match the hardware is worse than a missing one: it
    invites you to use it and then lies about the result.

    Label and room are deliberately *not* touched — those the owner chose, and
    the catalogue has no business overwriting them.

    Only genuine differences are written. A heartbeat arrives every five seconds
    and a write per heartbeat per device would be a busy loop wearing
    provisioning's clothes.
    """
    from app.features.device_store import update_device

    patch: Dict[str, Any] = {}

    # The widget the part needs. Owned by the catalogue, so a correction here
    # reaches devices that already exist.
    want_type = spec.get("control_type")
    if want_type and existing.get("control_type") != want_type:
        patch["control_type"] = want_type

    # Accepted values, placeholders, limits. Merged rather than replaced:
    # anything else in meta is the owner's.
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


def provision_for_owner(node_id: str, owner_id: str,
                        outputs: List[Dict[str, Any]],
                        label: str = "") -> Dict[str, Any]:
    """Provision on behalf of a tenant from a context that has none.

    The heartbeat path runs on the MQTT thread, outside any request, so it has no
    active tenant — and device_store deliberately writes nothing without one.
    This enters the owner's context just long enough to create their devices.

    The owner id comes from the node document, which was written when *that*
    tenant paired the code. So the only account this can ever write to is the one
    that already owns the node; a heartbeat cannot nominate its own owner.
    """
    from app.utils.user_profiles import active_user_profile_context

    if not owner_id:
        return {"ok": False, "error": "no_owner"}
    with active_user_profile_context(
        {"chat_id": owner_id, "permissions": "all", "relation": "user"}
    ):
        return provision_from_outputs(node_id, outputs, label)


def outputs_for_node(node_id: str) -> Optional[List[Dict[str, Any]]]:
    """The outputs a node last reported, read in the caller's tenant context."""
    from app.features.node_store import get_node

    node = get_node(node_id)
    if node is None:
        return None
    outs = node.get("outputs")
    return outs if isinstance(outs, list) else []
