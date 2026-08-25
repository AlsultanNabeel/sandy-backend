"""Node registry — paired Sandy nodes (the pre-flashed ESP boxes we sell).

A node is one physical ESP running the generic firmware. The customer powers it,
then **pairs** it in the app by entering the code printed on the box. Pairing binds
that code to the tenant; from then on the node's devices live under that tenant.

Collection: sandy_nodes (tenant-scoped via scoped())
  {
    _id, user_id (injected by scoped),
    node_id,           # our stable id for the node (generated at pairing)
    label,             # "صندوق الصالة"
    code_hash,         # sha256 of the factory pairing code (never store raw)
    capabilities,      # ["relay","pwm","servo","buzzer","ir","audio"] (node-reported)
    outputs,           # [{id:"relay1", kind:"relay"}, ...] (node-reported)
    firmware_version,
    online, last_seen, # heartbeat, for the diagnosis layer
    paired_at,
  }

Pure data: this module does not talk MQTT. The firmware reports heartbeat/caps
through the ingest path, which calls set_node_status().
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_nodes"

# سقف أمان، مش حد منتج — ما حدا بيوصله بالاستعمال العادي. موجود عشان
# خلل بالكتابة أو حساب دخل عليه إشي غريب ما يتحوّل لنداء بيسحب المجموعة
# كلها ويوقّع الطلب.
MAX_NODES = 100

# Capabilities a node may advertise. Validated so a bad heartbeat can't inject junk.
KNOWN_CAPABILITIES = frozenset({"relay", "pwm", "servo", "buzzer", "ir", "audio"})


def init_node_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("user_id", 1), ("node_id", 1)], unique=True, background=True
        )
        # Heartbeat ingest looks nodes up by code hash across tenants.
        mongo_db[_COLL].create_index([("code_hash", 1)], background=True)
        logger.info("[NodeStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("[NodeStore] index skipped: %s", e)


def _coll():
    """Tenant-scoped nodes collection, or None when no db / no active tenant."""
    return scoped(get_db(), _COLL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").strip().lower().encode("utf-8")).hexdigest()


def code_to_node_id(code: str) -> str:
    """Deterministic node_id from the printed pairing code: lowercase alphanumerics.

    The node is flashed with its code and derives the SAME id, so it knows its MQTT
    topic (sandy/node/<node_id>/...) before it is ever paired — no provisioning
    handshake needed. The firmware must apply this identical transform.
    """
    return re.sub(r"[^a-z0-9]", "", (code or "").strip().lower())


def _public(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "node_id": d.get("node_id", ""),
        "label": d.get("label", ""),
        "capabilities": d.get("capabilities", []),
        "outputs": d.get("outputs", []),
        "firmware_version": d.get("firmware_version", ""),
        "online": bool(d.get("online", False)),
        "last_seen": _iso(d.get("last_seen")),
        "paired_at": _iso(d.get("paired_at")),
        # Live readings from the last heartbeat — mic levels, current gains,
        # volume. A control screen needs these to draw a meter, and polling the
        # node list it already polls beats inventing a second endpoint.
        "telemetry": d.get("telemetry", {}),
    }


# What a heartbeat is allowed to report about itself. An allowlist, not a
# passthrough: the payload arrives over a shared broker from a device nobody has
# authenticated, so it may not write arbitrary keys into the node document.
_TELEMETRY_KEYS = {
    "mic_l": int, "mic_r": int,
    "mic_l_gain": int, "mic_r_gain": int,
    "mic_l_muted": bool, "mic_r_muted": bool,
    "volume": int, "noise": int,
    "uptime": int, "heap": int, "mood": int,
    # ما في "distance": حسّاس المسافة ملغي بقرار المالك ومش مركّب. قراءة
    # لجهاز غير موجود بتضل صفر للأبد، وبعد شهر حدا بيسأل ليش الروبوت لازق
    # بالحيط — فحذف الحقل أصدق من تركه.
    # نصوص قصيرة: عنوان اللوح ع الشبكة المحلية، واسم اللوح. العنوان بيتغيّر كل
    # ما الراوتر يعيد التوزيع، وبلا ما اللوح يقوله، إيجاده بيصير مسح وتخمين.
    "ip": str, "board": str,
    # سبب آخر إقلاع للكاميرا (رقم من اللوح). سبعة معناها انهيار كهربا — وهاد
    # الفرق بين «بدّها مزوّد أقوى» و«في خلل بالكود»، وهو فرق ما كان إله جواب.
    "cam_boot": int,
    # وعنوان الكاميرا بمفتاح مستقل.
    #
    # اللوحين بيشاركوا معرّف الوحدة والتليمتري بتندمج بالمفتاح، فحقل `ip` واحد
    # كان بينقلب بين الدماغ والكاميرا كل خمس ثواني. البثّ بيروح مباشرة من
    # الكاميرا لجهازك، فكان بيوجّه ع الدماغ نص الوقت — والدماغ ما عنده خادم
    # صور. فشل مرّة من كل مرّتين وما إله نمط يفسّره.
    "cam_ip": str, "cam_board": str, "cam_ssid": str,
    # اسم الشبكة اللي اللوح عليها. بيروح للتطبيق عشان تشوف الوضع قبل ما تغيّره،
    # وعشان النتيجة بعد التغيير تكون مقروءة من نفس المكان: اللوح اللي انتقل
    # بيقول الاسم الجديد، واللي رجع لحاله بيقول القديم. رسالة نجاح منفصلة كانت
    # بتصير مصدرًا تانيًا لنفس الحقيقة، والاتنين بيفترقوا يوم ما.
    "ssid": str,
    # قوّة الإشارة بالديسيبل ملّي واط — رقم سالب، وكل ما اقترب من الصفر أحسن.
    #
    # **الرقم الوحيد اللي بيفسّر «صوتي ما عم يوصل».** لهالعرض تلات أسباب بتبيّن
    # متطابقة ع وش الروبوت: رابط لاسلكي ضعيف، وخادم مشغول، ولوح ما بيلحق يرمّز.
    # الأول بينفصل عن التنتين بهالرقم لحاله — تحت خمسة وسبعين ناقص الوصلة ما
    # بتحمل صوتًا حيًّا مهما كان الباقي سليمًا.
    #
    # الكاميرا وعقدة الغرفة كانوا بيبعتوه، والدماغ لأ — وهو الوحيد اللي بيمرّر
    # صوتًا حيًّا. `room_rssi` بمفتاح مستقل لنفس سبب `cam_ip`: تلات ألواح تحت
    # معرّف واحد، وحقل واحد بينقلب بيناتهن كل خمس ثواني.
    "rssi": int, "room_rssi": int,
}


def _clean_telemetry(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, kind in _TELEMETRY_KEYS.items():
        if key not in data:
            continue
        try:
            if kind is bool:
                out[key] = bool(data[key])
            elif kind is str:
                # مقصوص: النبضة بتيجي من وسيط مشترك، فما منخزّن نص طويل بلا حد.
                out[key] = str(data[key])[:32]
            else:
                out[key] = int(data[key])
        except (TypeError, ValueError):
            continue   # a garbled field drops out; the rest still lands
    return out


def _clean_caps(caps: Any) -> List[str]:
    if not isinstance(caps, list):
        return []
    return [c for c in (str(x).strip().lower() for x in caps) if c in KNOWN_CAPABILITIES]


def _clean_outputs(outputs: Any) -> List[Dict[str, Any]]:
    """Validate node-reported outputs before storing them — a heartbeat is an
    untrusted, cross-tenant input (see mqtt_ingest), so a malformed/hostile
    payload can't inject arbitrary output definitions into the registry. Keep
    only well-formed {id, kind} entries with a known kind, and cap the count."""
    if not isinstance(outputs, list):
        return []
    clean: List[Dict[str, Any]] = []
    for o in outputs[:32]:
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id", "")).strip()[:32]
        kind = str(o.get("kind", "")).strip().lower()
        if oid and kind in KNOWN_CAPABILITIES:
            clean.append({"id": oid, "kind": kind})
    return clean


# ── Pairing ─────────────────────────────────────────────────────────────────

def _provision(node_id: str, outputs: Any, label: str = "") -> None:
    """Create the devices for a node's declared outputs, in the current tenant.

    Best-effort and never raises: pairing must succeed even if provisioning does
    not. A robot that paired but has no devices yet is recoverable — the next
    heartbeat provisions it. A pairing that failed because provisioning threw
    would leave the customer with a robot the app does not know about at all.
    """
    if not isinstance(outputs, list) or not outputs:
        return
    try:
        from app.features.node_provision import provision_from_outputs
        provision_from_outputs(node_id, outputs, label)
    except Exception as e:  # noqa: BLE001
        logger.warning("[NodeStore] provisioning %s failed: %s", node_id, e)


def _is_legacy_owner(user_id: Any) -> bool:
    """هل هالحساب هو حساب «المالك» القديم اللي ما عاد فيه دخول؟

    منفصلة عن مكان استعمالها لأنها **سؤال أمني**، وسؤال أمني لازم يكون مقروءًا
    لحاله: أي توسيع بالإجابة هون بيوسّع مين بيقدر ياخد روبوت حدا تاني.
    """
    if not user_id:
        return False
    try:
        from app.features import users_store
        owner = users_store.get_user(str(user_id)) or {}
        return str(owner.get("provider") or "") == "owner"
    except Exception:  # noqa: BLE001 — ما بنعرف يعني لأ، والافتراض الآمن الرفض
        return False


def pair_node(code: str, label: str = "") -> Dict[str, Any]:
    """Bind a factory pairing code to the current tenant.

    The raw code is hashed (never stored). Re-pairing the same code under the same
    tenant is a no-op that returns the existing node, so the flow is idempotent.
    """
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    code = (code or "").strip()
    if len(code) < 4:
        return {"ok": False, "error": "bad_code"}
    code_hash = _hash_code(code)

    existing = coll.find_one({"code_hash": code_hash})
    if existing is not None:
        # Already ours. Still provision: the first pairing may have happened
        # before the board ever sent a heartbeat, so this is where a robot that
        # was paired offline finally gets its parts.
        _provision(existing["node_id"], existing.get("outputs"),
                   existing.get("label", ""))
        return {"ok": True, "node_id": existing["node_id"], "already": True}

    # node_id = the code itself (slugified) so the firmware's topic is deterministic.
    node_id = code_to_node_id(code)
    if not node_id:
        return {"ok": False, "error": "bad_code"}

    # **مطالَبة مرّة وحدة — عبر كل الحسابات.**
    #
    # الفحص اللي فوق مقيّد بحساب المستخدم الحالي، يعني كان بيشوف «هل أنا ربطت
    # هالكود قبل؟» وبس. فحسابان مختلفان كانوا يقدروا يربطوا **نفس الروبوت**،
    # وكل واحد بياخد نسخته منه — والاتنين بيسمعوا نفس المواضيع.
    #
    # وهاد مش احتمال بعيد: الكود أربع خانات، يعني عشرة آلاف احتمال. أول حساب
    # بيربط بيملك، وبعدها اللوح مقفول لحدّ ما يترجع لضبط المصنع — زي أي جهاز
    # منزلي بينباع.
    if get_db() is not None:
        # لو فشلت القراءة ما بنكمل الربط: «ما قدرت أتأكد» لازم يوقف مطالبة
        # ملكية، مش يمرّرها. الفشل هون بيوقّف زبونًا صادقًا دقيقة، والعكس
        # بيعطي روبوتًا لحدا تاني.
        claimed = get_db()[_COLL].find_one({"node_id": node_id})
        if claimed is not None and not _is_legacy_owner(claimed.get("user_id")):
            logger.warning("[NodeStore] %s already claimed — refusing", node_id)
            return {"ok": False, "error": "already_claimed"}
        if claimed is not None:
            # **استثناء واحد: الحساب القديم اللي ما عاد فيه دخول.**
            #
            # قبل الحسابات الحقيقية، كل إشي كان تحت حساب اسمه «المالك» بيتصنع
            # من متغيّر بيئة، وبينداخل عليه بكلمة سرّ مشتركة. الكلمة انحذفت مع
            # مسار الدخول — يعني هالحساب صار **ما فيه طريقة تسجّل دخول عليه**.
            #
            # وبلا هالسطر، أول مالك بينقفل برّا روبوته للأبد: الروبوت مطالَب
            # بحساب ما بيقدر يوصله، وما في زرّ يفكّه. صاحب الجهاز بيخسره
            # بترقية.
            #
            # ضيّق بالقصد: بيمرّ بس لو المالك السابق هو ذاك الحساب تحديدًا.
            # أي حساب حقيقي تاني بيضلّ محميًّا.
            logger.info("[NodeStore] %s was held by the pre-accounts owner — "
                        "handing it to its new account", node_id)
            get_db()[_COLL].delete_one({"_id": claimed["_id"]})

    coll.insert_one({
        "node_id": node_id,
        "label": (label or "Sandy node").strip(),
        "code_hash": code_hash,
        "capabilities": [],
        "outputs": [],
        "firmware_version": "",
        "online": False,
        "paired_at": _now(),
    })
    return {"ok": True, "node_id": node_id, "already": False}


def list_nodes() -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    return [_public(d) for d in coll.find({}).sort("paired_at", 1).limit(MAX_NODES)]


def get_node(node_id: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return None
    return coll.find_one({"node_id": (node_id or "").strip()}) or None


def rename_node(node_id: str, label: str) -> Dict[str, Any]:
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    label = (label or "").strip()
    if not label:
        return {"ok": False, "error": "bad_label"}
    r = coll.update_one({"node_id": (node_id or "").strip()},
                        {"$set": {"label": label}})
    if r.matched_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "node_id": node_id}


def unpair_node(node_id: str) -> Dict[str, Any]:
    """Release a node **and everything that reaches the world through it.**

    Deleting the node row alone left the account still controlling the robot.
    A device row carries its own transport — `{"kind": "node", "node_id": …}` —
    and §2.7's boundary asks "does this topic actuate a device in the calling
    tenant's registry?", not "does the tenant still own the node". So the light
    and the neck and the face stayed in the app, stayed switchable, and kept
    publishing to a board that had just been sold.

    The board is not listening for permission either: its topics come from the
    pairing code compiled into it, so it obeys whatever arrives. Which is why
    this has to be a delete and not a flag.

    Returns the device count too — "unpaired" is not a checkable claim on its
    own, and this is the operation somebody performs while selling hardware.
    """
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    node_id = (node_id or "").strip()
    r = coll.delete_one({"node_id": node_id})
    if r.deleted_count == 0:
        return {"ok": False, "error": "not_found"}

    devices_removed = 0
    if node_id:
        from app.features.device_store import delete_devices_for_node

        devices_removed = delete_devices_for_node(node_id)
    return {"ok": True, "node_id": node_id, "devices_removed": devices_removed}


# ── Heartbeat ingest (called by the firmware-facing path, not tenant-scoped) ──

def set_node_status(code: str, online: bool = True,
                    capabilities: Optional[List[str]] = None,
                    outputs: Optional[List[Dict[str, Any]]] = None,
                    firmware_version: str = "") -> Dict[str, Any]:
    """Update a node's heartbeat by its pairing code (firmware speaks code, not
    node_id). Looked up across tenants by code hash. Best-effort; never raises."""
    if get_db() is None:
        return {"ok": False, "error": "no_store"}
    try:
        update: Dict[str, Any] = {"online": bool(online), "last_seen": _now()}
        if capabilities is not None:
            update["capabilities"] = _clean_caps(capabilities)
        if isinstance(outputs, list):
            # This path is keyed by pairing code, not node id, so the merge needs
            # the id looked up first — the same two-boards-one-node rule applies
            # here as on the heartbeat path, and having one of them replace while
            # the other merges is exactly the kind of split that produces a bug
            # nobody can reproduce.
            existing = get_db()[_COLL].find_one({"code_hash": _hash_code(code)},
                                                {"node_id": 1})
            update["outputs"] = _merge_outputs(
                str((existing or {}).get("node_id", "")), outputs)
        if firmware_version:
            update["firmware_version"] = str(firmware_version)[:32]
        r = get_db()[_COLL].update_one(
            {"code_hash": _hash_code(code)}, {"$set": update}
        )
        if r.matched_count == 0:
            return {"ok": False, "error": "unknown_node"}
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.debug("[NodeStore] set_node_status failed: %s", e)
        return {"ok": False, "error": "exception"}


# ── MQTT ingest (firmware speaks node_id in the topic; runs outside a tenant) ──

# ── Two boards, one node ─────────────────────────────────────────────────────
#
# The brain and the camera share a node id: the camera is part of Sandy, not a
# second box. So two different heartbeats arrive five seconds apart, each
# describing a different half of the same robot.
#
# Replacing on write made them erase each other in a loop. The brain's heartbeat
# wiped every `cam/` output; the camera's wiped the microphone levels and the
# brain's address; five seconds later the brain wiped the camera's. Whatever you
# asked for was there roughly half the time, and which half depended on when you
# looked — so "the camera has no address" and "the address is fine" were both
# true, minutes apart, with nothing changed in between.
#
# So both merge. A heartbeat now says what its own board has and stays silent
# about the other's, which is all it ever knew anyway.

def _output_namespace(output_id: Any) -> str:
    """Which board a declared output belongs to.

    Several boards answer under one node id — they are one robot, not three
    boxes — and each writes in its own prefix: the camera under ``cam/``, the
    room node under ``room/``, the brain in the bare namespace. The prefix is
    the boundary, so this is the one place that reads it.
    """
    oid = str(output_id or "")
    head, sep, _ = oid.partition("/")
    return head + sep if sep else ""


def _merge_outputs(node_id: str, incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace only the namespaces this heartbeat speaks for.

    Two heartbeats arriving five seconds apart would otherwise take turns wiping
    each other out, and the app would flicker between a robot with a neck and a
    robot with a flash.

    This used to be a boolean — camera or not — which was right while there were
    exactly two boards and silently wrong the moment a third arrived: the room
    node's outputs counted as "not camera", so every brain heartbeat deleted the
    room and every room heartbeat deleted the brain. Namespaces are what the rule
    was always about; the boolean was a two-board shortcut.

    A heartbeat that declares nothing keeps everything. Silence is not a claim
    that the hardware is gone.
    """
    fresh = _clean_outputs(incoming)
    claimed = {_output_namespace(o.get("id")) for o in fresh}

    existing = (get_node_any_tenant(node_id) or {}).get("outputs") or []
    kept = [
        o for o in existing
        if isinstance(o, dict) and _output_namespace(o.get("id")) not in claimed
    ]
    return kept + fresh


def _merge_telemetry(node_id: str, incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Update the keys this heartbeat carries; leave the others alone.

    A camera heartbeat has no opinion about the microphone levels, and a brain
    heartbeat has none about the camera. Overwriting with silence is not a
    correction — it is forgetting.
    """
    fresh = _clean_telemetry(incoming)
    existing = (get_node_any_tenant(node_id) or {}).get("telemetry") or {}
    if not isinstance(existing, dict):
        existing = {}
    return {**existing, **fresh}


def get_node_any_tenant(node_id: str) -> Optional[Dict[str, Any]]:
    """One node by id, from the raw collection, ignoring tenant scope.

    Only for the ingest path, which runs on the MQTT thread with no tenant
    context — the same reason ingest_status reads raw. Never expose this to a
    request handler: it can see every tenant's nodes, and that is exactly what
    the scoped reads exist to prevent.
    """
    if get_db() is None:
        return None
    try:
        return get_db()[_COLL].find_one({"node_id": (node_id or "").strip()})
    except Exception:  # noqa: BLE001
        return None


def ingest_status(node_id: str, online: bool = True,
                  capabilities: Optional[List[str]] = None,
                  outputs: Optional[List[Dict[str, Any]]] = None,
                  firmware_version: str = "",
                  telemetry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Heartbeat update keyed by node_id (the firmware publishes by node_id, not
    code). Cross-tenant lookup on the raw collection; best-effort, never raises."""
    if get_db() is None:
        return {"ok": False, "error": "no_store"}
    try:
        update: Dict[str, Any] = {"online": bool(online), "last_seen": _now()}
        if capabilities is not None:
            update["capabilities"] = _clean_caps(capabilities)
        if isinstance(outputs, list):
            update["outputs"] = _merge_outputs(node_id, outputs)
        if firmware_version:
            update["firmware_version"] = str(firmware_version)[:32]
        if telemetry is not None:
            update["telemetry"] = _merge_telemetry(node_id, telemetry)
        node_id = (node_id or "").strip()
        r = get_db()[_COLL].update_one({"node_id": node_id}, {"$set": update})
        if r.matched_count == 0:
            # A heartbeat from a board nobody has paired yet. Normal: the robot
            # is powered on and shouting its node_id into the broker, waiting for
            # someone to type its code. Nothing to do until then.
            return {"ok": False}

        # Newly declared outputs become devices its owner can drive. Doing it
        # here — rather than only at pairing — is what makes a firmware upgrade
        # that adds a part show up in the app on its own, with nobody re-pairing
        # anything.
        if update.get("outputs"):
            doc = get_db()[_COLL].find_one({"node_id": node_id},
                                           {"user_id": 1, "label": 1})
            if doc and doc.get("user_id"):
                from app.features.node_provision import provision_for_owner
                provision_for_owner(node_id, str(doc["user_id"]),
                                    update["outputs"], str(doc.get("label", "")))
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.debug("[NodeStore] ingest_status failed: %s", e)
        return {"ok": False, "error": "exception"}


def set_last_ir(node_id: str, code: str) -> Dict[str, Any]:
    """Record the most recent IR code a node captured in learn mode, so the app can
    poll for it and bind it to a button. Keyed by node_id, cross-tenant."""
    if get_db() is None:
        return {"ok": False, "error": "no_store"}
    try:
        r = get_db()[_COLL].update_one(
            {"node_id": (node_id or "").strip()},
            {"$set": {"last_ir": str(code).strip(), "last_ir_at": _now()}},
        )
        return {"ok": r.matched_count > 0}
    except Exception as e:  # noqa: BLE001
        logger.debug("[NodeStore] set_last_ir failed: %s", e)
        return {"ok": False, "error": "exception"}


def get_last_ir(node_id: str) -> Dict[str, Any]:
    """The last captured IR code for a node (tenant-scoped read for the app)."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    d = coll.find_one({"node_id": (node_id or "").strip()})
    if d is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "code": d.get("last_ir", ""), "at": _iso(d.get("last_ir_at"))}
