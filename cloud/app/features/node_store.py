"""Node registry (sandy_nodes): paired Sandy boards, bound to a tenant by the code on the box.

Stores node_id, label, code_hash (never the raw code), capabilities, outputs,
firmware_version, online/last_seen, telemetry, paired_at. Pure data: heartbeats
arrive via integrations/mqtt_ingest.py → ingest_status().
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.db import configure, get_db

from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)

_COLL = "sandy_nodes"

# سقف أمان، مش حد منتج.
MAX_NODES = 100

KNOWN_CAPABILITIES = frozenset({"relay", "pwm", "servo", "buzzer", "ir", "audio"})

# A board nobody paired is heard here, keyed by its id (its heartbeat is otherwise dropped),
# so pairing can say «not connected» instead of sending its face a code it will never show.
_SIGHTINGS = "node_sightings"
# Its heartbeat comes every five seconds: six missed is gone.
PRESENT_WITHIN = timedelta(seconds=30)

# A release's erase, kept until the board shows it was wiped: the erase goes once on a
# broker that keeps nothing for a clean session, so a board off at release kept the
# seller's Wi-Fi and broker login for ever while the app said done.
_PENDING_ERASE = "node_pending_erase"
# Sent again on its heartbeats, at most this often.
ERASE_RESEND = timedelta(minutes=1)
# Long enough for a robot in a box between owners; past it the row goes by itself.
ERASE_KEPT_DAYS = 30


def init_node_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    # One try each: a failed one must not skip the rest, least of all the uniqueness ones.
    jobs = [
        ("user_id+node_id", lambda: mongo_db[_COLL].create_index(
            [("user_id", 1), ("node_id", 1)], unique=True, background=True)),
        # Heartbeat ingest looks nodes up by code hash across tenants.
        ("code_hash", lambda: mongo_db[_COLL].create_index(
            [("code_hash", 1)], background=True)),
        # One owner per board, enforced by the database (the read-then-insert check races).
        ("node_id_owner_unique", lambda: mongo_db[_COLL].create_index(
            [("node_id", 1)], unique=True, background=True, name="node_id_owner_unique")),
        # One robot per account (the owner's decision). Not built over an account that has
        # two already: that is logged here and left to the owner, never unpaired by itself.
        ("one_robot_per_account", lambda: mongo_db[_COLL].create_index(
            [("user_id", 1)], unique=True, background=True, name="one_robot_per_account")),
        # A sighting is only for pairing now: a day old is long gone.
        ("node_sightings.last_seen_ttl", lambda: mongo_db[_SIGHTINGS].create_index(
            "last_seen", expireAfterSeconds=24 * 3600, background=True)),
        ("node_pending_erase.since_ttl", lambda: mongo_db[_PENDING_ERASE].create_index(
            "since", expireAfterSeconds=ERASE_KEPT_DAYS * 24 * 3600, background=True)),
    ]
    for label, job in jobs:
        try:
            job()
        except PyMongoError as e:
            logger.warning("[NodeStore] index %s skipped: %s", label, e)
    logger.info("[NodeStore] ready")


def _coll():
    return scoped(get_db(), _COLL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").strip().lower().encode("utf-8")).hexdigest()


def code_to_node_id(code: str) -> str:
    """node_id from the printed pairing code (lowercase alphanumerics); the firmware applies the same transform."""
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
        "telemetry": d.get("telemetry", {}),
    }


# Allowlist: heartbeats come from unauthenticated devices over a shared broker.
_TELEMETRY_KEYS = {
    "mic_l": int, "mic_r": int,
    "mic_l_gain": int, "mic_r_gain": int,
    "mic_l_muted": bool, "mic_r_muted": bool,
    "volume": int,
    "uptime": int, "heap": int, "mood": int,
    # Boards share a node id, so each board's fields get their own prefix.
    "ip": str, "board": str,
    "cam_boot": int,
    "cam_ip": str, "cam_board": str, "cam_ssid": str,
    # cam_stream_key: random per boot; the app needs it to open the local stream.
    "cam_fw": str, "cam_online": bool, "cam_stream_key": str,
    "room_ip": str, "room_board": str, "room_light": str,
    "room_fw": str, "room_online": bool, "room_uptime_s": int, "room_heap": int,
    "ssid": str,
    # dBm; below about -75 the link can't carry live voice.
    "rssi": int, "room_rssi": int,
    # The brain's health: last reset reason, restarts ever, least internal RAM it had,
    # its largest block now, safe mode, each part not OK, each task's least stack headroom.
    "boot": int, "boots": int, "heap_min": int, "heap_big": int, "safe": bool,
    # The settings store: erased at this boot to recover (Wi-Fi and keys lost), and how full.
    "nvs_wiped": bool, "nvs_used": int, "nvs_total": int,
    "faults": dict, "stacks": dict,
}

# A dict member: a few short names to a short string or a number.
_DICT_MAX_ITEMS = 24


def _clean_telemetry(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, kind in _TELEMETRY_KEYS.items():
        if key not in data:
            continue
        try:
            if kind is dict:
                if isinstance(data[key], dict):
                    out[key] = {
                        str(k)[:16]: (v if isinstance(v, int) and not isinstance(v, bool)
                                      else str(v)[:32])
                        for k, v in list(data[key].items())[:_DICT_MAX_ITEMS]
                    }
            elif kind is bool:
                out[key] = bool(data[key])
            elif kind is str:
                # Capped: untrusted input.
                out[key] = str(data[key])[:32]
            else:
                out[key] = int(data[key])
        except (TypeError, ValueError):
            continue
    return out


def _clean_caps(caps: Any) -> List[str]:
    if not isinstance(caps, list):
        return []
    return [c for c in (str(x).strip().lower() for x in caps) if c in KNOWN_CAPABILITIES]


def _clean_outputs(outputs: Any) -> List[Dict[str, Any]]:
    """Keep only well-formed {id, kind} outputs with a known kind (untrusted heartbeat input)."""
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
    """Create devices for declared outputs in the current tenant; never fails a pairing."""
    if not isinstance(outputs, list) or not outputs:
        return
    try:
        from app.features.node_provision import provision_from_outputs
        provision_from_outputs(node_id, outputs, label)
    except Exception as e:  # noqa: BLE001
        logger.warning("[NodeStore] provisioning %s failed: %s", node_id, e)


def _is_legacy_owner(user_id: Any) -> bool:
    """هل هالحساب هو حساب «المالك» القديم (ما عاد فيه دخول)؟ سؤال أمني: أي توسيع بيسمح بأخذ روبوت حدا تاني."""
    if not user_id:
        return False
    try:
        from app.features import users_store
        owner = users_store.get_user(str(user_id)) or {}
        return str(owner.get("provider") or "") == "owner"
    except Exception:  # noqa: BLE001 — الافتراض الآمن الرفض
        return False


def _has_another_robot(coll, node_id: str) -> bool:
    """One robot per account: the caller already paired a board other than this one. The
    camera and the room node share their robot's id, so they are never «another»."""
    return coll.find_one({"node_id": {"$ne": node_id}}, {"_id": 1}) is not None


def pair_precheck(code: str) -> Dict[str, Any]:
    """Pairing state before writing: ``ours``, ``claimed`` by another account,
    ``one_robot`` (this account has another), or ``free``."""
    code = (code or "").strip()
    node_id = code_to_node_id(code)
    if len(code) < 4 or not node_id:
        return {"state": "bad_code"}
    coll = _coll()
    if coll is None:
        return {"state": "no_store"}
    if coll.find_one({"code_hash": _hash_code(code)}) is not None:
        return {"state": "ours", "node_id": node_id}
    if get_db() is not None:
        claimed = get_db()[_COLL].find_one({"node_id": node_id})
        if claimed is not None and not _is_legacy_owner(claimed.get("user_id")):
            return {"state": "claimed", "node_id": node_id}
    if _has_another_robot(coll, node_id):
        return {"state": "one_robot", "node_id": node_id}
    return {"state": "free", "node_id": node_id}


def pair_node(code: str, label: str = "") -> Dict[str, Any]:
    """Bind a factory pairing code to the current tenant (idempotent for the same tenant)."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    code = (code or "").strip()
    if len(code) < 4:
        return {"ok": False, "error": "bad_code"}
    code_hash = _hash_code(code)

    existing = coll.find_one({"code_hash": code_hash})
    if existing is not None:
        # Already ours; still provision (it may have paired before any heartbeat).
        _provision(existing["node_id"], existing.get("outputs"),
                   existing.get("label", ""))
        _open_key_enrolment(existing["node_id"])
        return {"ok": True, "node_id": existing["node_id"], "already": True}

    node_id = code_to_node_id(code)
    if not node_id:
        return {"ok": False, "error": "bad_code"}
    if _has_another_robot(coll, node_id):
        return {"ok": False, "error": "one_robot"}
    # Paired again, by anyone: an erase still waiting from its last release must never
    # reach it. Dropped before the claim, so an erase on its way finds nothing to send.
    if get_db() is not None:
        get_db()[_PENDING_ERASE].delete_one({"_id": node_id})

    # مطالَبة مرّة وحدة عبر كل الحسابات: أول حساب بيربط بيملك.
    if get_db() is not None:
        # لو فشلت القراءة ما بنكمل: «ما قدرت أتأكد» لازم يوقف المطالبة.
        claimed = get_db()[_COLL].find_one({"node_id": node_id})
        if claimed is not None and not _is_legacy_owner(claimed.get("user_id")):
            logger.warning("[NodeStore] %s already claimed — refusing", node_id)
            return {"ok": False, "error": "already_claimed"}
        if claimed is not None:
            # استثناء ضيّق: الحساب «المالك» القديم ما فيه دخول، فبدونه صاحب الروبوت بينقفل برّاه.
            logger.info("[NodeStore] %s was held by the pre-accounts owner — "
                        "handing it to its new account", node_id)
            get_db()[_COLL].delete_one({"_id": claimed["_id"]})

    try:
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
    except DuplicateKeyError:
        # Either index: this board went to another account, or this account paired
        # another board at the same moment (`one_robot_per_account`).
        if _has_another_robot(coll, node_id):
            return {"ok": False, "error": "one_robot"}
        logger.warning("[NodeStore] %s claimed concurrently — refusing", node_id)
        return {"ok": False, "error": "already_claimed"}
    _open_key_enrolment(node_id)
    return {"ok": True, "node_id": node_id, "already": False}


def _open_key_enrolment(node_id: str) -> None:
    """Pairing is when the owner vouches for the board: open its voice-key enrolment."""
    try:
        from app.features.device_keys import cam_key_id, open_enrolment
        open_enrolment(node_id)
        open_enrolment(cam_key_id(node_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NodeStore] key enrolment not opened for %s: %s", node_id, exc)


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


def _erase_command(node_id: str, key: Optional[bytes] = None) -> Optional[str]:
    """``erase:<ms>:<hmac>``, signed like the voice hello: with ``key``, else the board's
    own key, or the shared one while it has none. The board refuses anything unsigned or
    more than five minutes old, so a word on the broker can no longer wipe a robot."""
    import hashlib
    import hmac
    import time

    from app.api.voice_ws._config import _HMAC_KEY
    from app.features.device_keys import get_key

    if key is None:
        record = get_key(node_id)
        key = record["key"] if record else _HMAC_KEY
    if not key:
        return None
    ms = str(int(time.time() * 1000))
    mac = hmac.new(key, f"factory_reset|{node_id}|{ms}".encode(), hashlib.sha256).hexdigest()
    return f"erase:{ms}:{mac}"


def _wipe_board(node_id: str) -> bool:
    """Tell the board to forget its network credentials. Best effort."""
    try:
        from app.integrations.room_device import get_room_device_client

        command = _erase_command(node_id)
        if not command:
            logger.warning("[NodeStore] no key to sign the factory reset of %s", node_id)
            return False
        return bool(get_room_device_client().publish_service(
            f"sandy/node/{node_id}/factory_reset", command))
    except Exception as exc:  # noqa: BLE001 — an offline board must not block the release
        logger.warning("[NodeStore] factory reset not delivered to %s: %s",
                       node_id, exc)
        return False


def unpair_node(node_id: str) -> Dict[str, Any]:
    """Release a node and every device that actuates through it.

    The board obeys any topic built from its code, so its devices must be deleted,
    not flagged. Returns the device count and whether the board was wiped.
    """
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    node_id = (node_id or "").strip()
    node = coll.find_one({"node_id": node_id})
    if not node:
        return {"ok": False, "error": "not_found"}

    # Wipe the board first, while the caller still owns it (account deletion also
    # comes through here). An offline board doesn't block the release. «Wiped» only when
    # it was there to take it: the broker keeps nothing for a board that is off.
    board_wiped = _wipe_board(node_id) and part_present(node, "") is True
    # Whether it took is unknown (no word comes back): keep it until the board shows it.
    _keep_erase(node_id)

    from app.features.device_store import delete_devices_for_node

    # Devices before the node row, so a racing heartbeat can't re-provision them.

    devices_removed = delete_devices_for_node(node_id)
    if devices_removed is None:
        # Its devices would outlive it, with nothing left to refuse them: stop here.
        return {"ok": False, "error": "release_failed", "board_wiped": board_wiped}
    # A sold robot must enrol a fresh voice key.
    try:
        from app.features.device_keys import cam_key_id, revoke_key
        revoke_key(node_id)
        revoke_key(cam_key_id(node_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NodeStore] could not revoke the voice key of %s: %s",
                       node_id, exc)
    r = coll.delete_one({"node_id": node_id})
    if r.deleted_count == 0:
        return {"ok": False, "error": "not_found",
                "devices_removed": devices_removed, "board_wiped": board_wiped}
    return {"ok": True, "node_id": node_id,
            "devices_removed": devices_removed, "board_wiped": board_wiped,
            "erase_pending": True}


def _keep_erase(node_id: str) -> None:
    """The release's erase, kept for the board's next heartbeats (`_erase_if_pending`):
    its own key, sealed (it is revoked next and the board still checks with it), and the
    restart count and network it had, which is how its wipe shows (both reset or change)."""
    from app.features.device_keys import KeyUnreadable, get_key
    from app.utils.ltm_crypto import encrypt_field

    db = get_db()
    if db is None:
        return
    try:
        record = get_key(node_id)
        node = db[_COLL].find_one({"node_id": node_id}) or {}
        tel = node.get("telemetry") or {}
        db[_PENDING_ERASE].update_one({"_id": node_id}, {"$set": {
            "key": encrypt_field(record["hex"]) if record else None,
            "boots": tel.get("boots") if isinstance(tel.get("boots"), int) else None,
            "ssid": str(tel.get("ssid") or "") or None,
            "since": _now(), "sent_at": None,
        }}, upsert=True)
    except (PyMongoError, KeyUnreadable) as exc:  # the release itself must still go through
        logger.warning("[NodeStore] erase of %s not kept for later: %s", node_id, exc)


def _erase_if_pending(node_id: str, telemetry: Dict[str, Any]) -> None:
    """A released board's heartbeat: send its erase again, unless it shows it was wiped
    (its restart count fell below the one at release, or it is on another network), or it
    belongs to an account again, which it is never sent to."""
    from app.utils.ltm_crypto import decrypt_field

    db = get_db()
    pending = db[_PENDING_ERASE].find_one({"_id": node_id})
    if pending is None:
        return
    tel = telemetry if isinstance(telemetry, dict) else {}
    boots, ssid = tel.get("boots"), str(tel.get("ssid") or "")
    wiped = (isinstance(boots, int) and isinstance(pending.get("boots"), int)
             and boots < pending["boots"])
    moved = bool(ssid and pending.get("ssid") and ssid != pending["ssid"])
    if wiped or moved:
        db[_PENDING_ERASE].delete_one({"_id": node_id})
        logger.info("[NodeStore] %s shows it was wiped (%s); erase dropped", node_id,
                    "restart count reset" if wiped else "another network")
        return
    # Claimed by the send, at most once a minute across workers.
    now = _now()
    claimed = db[_PENDING_ERASE].find_one_and_update(
        {"_id": node_id, "$or": [{"sent_at": None}, {"sent_at": {"$lt": now - ERASE_RESEND}}]},
        {"$set": {"sent_at": now}})
    if claimed is None:
        return
    if get_node_any_tenant(node_id) is not None:
        # Paired again while this ran: never wipe someone's robot.
        db[_PENDING_ERASE].delete_one({"_id": node_id})
        return
    from app.api.voice_ws._config import _HMAC_KEY
    from app.integrations.room_device import get_room_device_client

    # It checks with one key: its own if it still has one, else the shared. Both go.
    own = bytes.fromhex(decrypt_field(claimed["key"])) if claimed.get("key") else None
    for key in [k for k in (own, _HMAC_KEY) if k]:
        command = _erase_command(node_id, key)
        if command:
            get_room_device_client().publish_service(
                f"sandy/node/{node_id}/factory_reset", command)
    logger.info("[NodeStore] erase sent again to released board %s", node_id)


# ── Heartbeat ingest (firmware-facing, runs outside a tenant) ────────────────
# Several boards share one node id; each heartbeat merges only its own board's
# outputs and telemetry, or they erase each other in a loop.

def _output_namespace(output_id: Any) -> str:
    """The board prefix of an output id: ``cam/``, ``room/``, or "" for the brain."""
    oid = str(output_id or "")
    head, sep, _ = oid.partition("/")
    return head + sep if sep else ""


def part_present(node: Optional[Dict[str, Any]], output: Any) -> Optional[bool]:
    """Whether the board that serves ``output`` is there now.

    False when it said it went (its MQTT will: ``online`` for the brain, ``cam_online`` and
    ``room_online`` for the others) or, for the brain, when it runs in safe mode, which takes
    none of its outputs; None when that board was never heard from.
    """
    if not node:
        return None
    tel = node.get("telemetry") or {}
    ns = _output_namespace(output)
    if ns == "cam/":
        return tel.get("cam_online") if isinstance(tel.get("cam_online"), bool) else None
    if ns == "room/":
        return tel.get("room_online") if isinstance(tel.get("room_online"), bool) else None
    if ns:
        return None
    if not node.get("last_seen"):
        return None
    return bool(node.get("online")) and not tel.get("safe")


def _merge_outputs(node_id: str, incoming: List[Dict[str, Any]],
                   current: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Replace only the namespaces this heartbeat declares; declaring nothing keeps everything.

    ``current`` is the node document when the caller already read it.
    """
    fresh = _clean_outputs(incoming)
    claimed = {_output_namespace(o.get("id")) for o in fresh}

    if current is None:
        current = get_node_any_tenant(node_id) or {}
    existing = current.get("outputs") or []
    kept = [
        o for o in existing
        if isinstance(o, dict) and _output_namespace(o.get("id")) not in claimed
    ]
    return kept + fresh


def _merge_telemetry(current: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Update only the keys this heartbeat carries."""
    fresh = _clean_telemetry(incoming)
    existing = current.get("telemetry") or {}
    if not isinstance(existing, dict):
        existing = {}
    return {**existing, **fresh}


def get_node_any_tenant(node_id: str) -> Optional[Dict[str, Any]]:
    """One node by id across tenants — ingest path only, never a request handler."""
    if get_db() is None:
        return None
    try:
        return get_db()[_COLL].find_one({"node_id": (node_id or "").strip()})
    except Exception:  # noqa: BLE001
        return None


def ingest_status(node_id: str, online: Optional[bool] = True,
                  capabilities: Optional[List[str]] = None,
                  outputs: Optional[List[Dict[str, Any]]] = None,
                  firmware_version: str = "",
                  telemetry: Optional[Dict[str, Any]] = None,
                  heard: bool = True) -> Dict[str, Any]:
    """Heartbeat update by node_id, cross-tenant; best-effort, never raises.

    ``online=None`` leaves online/last_seen alone (camera and room node report their own).
    ``heard=False`` (the broker's retained copy) keeps last_seen: it is not the board now.
    """
    if get_db() is None:
        return {"ok": False, "error": "no_store"}
    try:
        node_id = (node_id or "").strip()
        # Read once; both merges and provisioning use it.
        current = get_node_any_tenant(node_id)
        if current is None:
            # Not paired yet: only that it is there, for pairing, and an erase it still owes.
            if online is not None and heard:
                tel = telemetry if isinstance(telemetry, dict) else {}
                get_db()[_SIGHTINGS].update_one(
                    {"_id": node_id},
                    {"$set": {"online": bool(online), "safe": bool(tel.get("safe")),
                              "last_seen": _now()}},
                    upsert=True)
                if online:
                    _erase_if_pending(node_id, tel)
            return {"ok": False}
        update: Dict[str, Any] = {}
        if online is not None:
            update["online"] = bool(online)
            if heard:
                update["last_seen"] = _now()
        if capabilities is not None:
            update["capabilities"] = _clean_caps(capabilities)
        if isinstance(outputs, list):
            update["outputs"] = _merge_outputs(node_id, outputs, current)
        if firmware_version:
            update["firmware_version"] = str(firmware_version)[:32]
        if telemetry is not None:
            update["telemetry"] = _merge_telemetry(current, telemetry)
        if not update:
            return {"ok": True}
        r = get_db()[_COLL].update_one({"node_id": node_id}, {"$set": update})
        if r.matched_count == 0:
            return {"ok": False}   # unpaired between the read and the write

        # New outputs become devices, so a firmware upgrade shows up without re-pairing.
        if update.get("outputs") and current.get("user_id"):
            from app.features.node_provision import provision_for_owner
            provision_for_owner(node_id, str(current["user_id"]),
                                update["outputs"], str(current.get("label", "")))
        # What the board says its volume and mics are, so «a little lower» starts from there.
        if telemetry and current.get("user_id"):
            from app.features.node_provision import states_for_owner
            states_for_owner(node_id, str(current["user_id"]), telemetry)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.debug("[NodeStore] ingest_status failed: %s", e)
        return {"ok": False, "error": "exception"}


def unpaired_board_present(node_id: str) -> bool:
    """A board nobody paired is there and can show a pairing code: its last heartbeat came
    within `PRESENT_WITHIN`, it did not say it went (its MQTT will), and it is not in safe
    mode (which takes no pairing code). A board on its setup network, on a wrong network or
    switched off sends none."""
    db = get_db()
    if db is None:
        return False
    try:
        doc = db[_SIGHTINGS].find_one({"_id": (node_id or "").strip()})
    except PyMongoError as exc:
        logger.warning("[NodeStore] sighting of %s not read: %s", node_id, exc)
        return False
    if not doc or not doc.get("online") or doc.get("safe"):
        return False
    seen = doc.get("last_seen")
    if not isinstance(seen, datetime):
        return False
    seen = seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)
    return _now() - seen <= PRESENT_WITHIN


def set_last_ir(node_id: str, code: str) -> Dict[str, Any]:
    """Record the last IR code a node captured in learn mode (cross-tenant)."""
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
    """The last captured IR code for a node (tenant-scoped)."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    d = coll.find_one({"node_id": (node_id or "").strip()})
    if d is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "code": d.get("last_ir", ""), "at": _iso(d.get("last_ir_at"))}
