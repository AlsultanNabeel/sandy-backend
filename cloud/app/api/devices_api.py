"""Control-tab API: device registry, node pairing, direct control, camera. Guests get nothing.

  GET/POST /api/devices · PATCH/DELETE /api/devices/<name>
  POST /api/devices/<name>/control {action,value?} · /image {image_base64} · /ir-learn {button,code}
  GET /api/nodes · POST /api/nodes/pair {code,label?} · POST /api/nodes/pair/confirm {code,presence,label?}
  PATCH/DELETE /api/nodes/<node_id> · POST /api/nodes/<node_id>/wifi {ssid,password,board?}
  POST /api/nodes/<node_id>/snapshot · GET /api/nodes/<node_id>/snapshot/<req_id>
  POST /api/nodes/<node_id>/ir/learn · GET /api/nodes/<node_id>/ir/last
  POST /api/cam/upload (HMAC, no session) · GET /api/diagnose
"""

from __future__ import annotations

import logging
import re
import time

from flask import Response, jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
)

logger = logging.getLogger(__name__)


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"


# رفع الكاميرا: شكل المعرّفات، وسقف الحجم، وبصمات التواقيع المستعملة.
_CAM_NODE_RE = re.compile(r"[a-z0-9]{1,32}")
# A free robot is claimed only with the code shown on its own screen; turning
# this off means a photo of the box is enough to take someone's robot.
PAIR_NEEDS_PRESENCE = True
_CAM_REQ_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
_CAM_MAX_UPLOAD_BYTES = 512 * 1024
_CAM_NONCES = "cam_upload_nonces"


def _cam_signature_fresh(sig: str) -> bool:
    """True the first time a signature is seen (stored in Mongo so both workers agree; fails open without a db)."""
    from datetime import datetime, timedelta, timezone

    from pymongo.errors import DuplicateKeyError, PyMongoError

    from app.db import get_db

    db = get_db()
    if db is None:
        return True
    try:
        db[_CAM_NONCES].insert_one({
            "_id": sig[:80],
            "expire_at": datetime.now(timezone.utc) + timedelta(minutes=3),
        })
        return True
    except DuplicateKeyError:
        return False
    except PyMongoError:
        return True


def _bad(error: str, extra: dict | None = None, code: int = 400):
    body = {"error": error}
    if extra:
        body.update(extra)
    return jsonify(body), code


def register_devices_api(app, mongo_db=None):
    # ── Devices ─────────────────────────────────────────────────────────────
    @app.route("/api/devices", methods=["GET"])
    @require_auth
    def api_devices_list(claims):
        if _is_guest(claims):
            return jsonify({"items": [], "demo": True}), 200
        from app.features.device_store import list_devices

        with active_user_profile_context(build_user_profile(claims)):
            return jsonify({"items": list_devices(), "demo": False}), 200

    @app.route("/api/devices", methods=["POST"])
    @require_tenant
    def api_devices_add(claims):
        from app.features.device_store import add_device

        body = request.get_json(silent=True) or {}
        r = add_device(
            name=body.get("name", ""),
            label=body.get("label", ""),
            control_type=body.get("control_type", ""),
            transport=body.get("transport", {}),
            room=body.get("room", ""),
            meta=body.get("meta") or {},
        )
        if not r.get("ok"):
            return _bad(r.get("error", "add_failed"),
                        {"allowed": r.get("allowed")} if r.get("allowed") else None)
        return jsonify(r), 200

    @app.route("/api/devices/<name>", methods=["PATCH"])
    @require_tenant
    def api_devices_update(claims, name):
        from app.features.device_store import update_device

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _bad("invalid_request")
        # Only patchable fields: a `name` key would collide with the positional arg.
        fields = {k: body[k] for k in ("label", "room", "control_type", "transport", "meta")
                  if k in body}
        r = update_device(name, **fields)
        if not r.get("ok"):
            return _bad(r.get("error", "update_failed"),
                        {"allowed": r.get("allowed")} if r.get("allowed") else None)
        return jsonify(r), 200

    @app.route("/api/devices/<name>", methods=["DELETE"])
    @require_tenant
    def api_devices_delete(claims, name):
        from app.features.device_store import delete_device

        r = delete_device(name)
        if not r.get("ok"):
            return _bad(r.get("error", "delete_failed"), code=404)
        return jsonify(r), 200

    @app.route("/api/devices/<name>/control", methods=["POST"])
    @require_tenant
    def api_devices_control(claims, name):
        from app.features.device_store import (
            command_payload,
            device_topic,
            get_device,
            set_state,
        )
        from app.integrations.room_device import get_room_device_client

        body = request.get_json(silent=True) or {}
        device = get_device(name)
        if device is None:
            return _bad("not_found", code=404)
        res = command_payload(device, body.get("action", ""), body.get("value", ""))
        if not res.get("ok"):
            return _bad(res.get("error", "bad_command"),
                        {"allowed": res.get("allowed")})
        topic = device_topic(device)
        if not topic:
            return _bad("bad_transport")
        payload = res["payload"]
        sent = False
        try:
            sent = get_room_device_client().send_to_topic(topic, payload)
        except Exception:  # noqa: BLE001 — control must not 500
            sent = False
        if sent:
            set_state(name, payload)
        return jsonify({"ok": True, "sent": sent, "payload": payload}), 200

    @app.route("/api/nodes/<node_id>/wifi", methods=["POST"])
    @require_tenant
    def api_node_wifi(claims, node_id):
        """Ask one board to switch networks; returns once sent (the next heartbeat's `ssid` shows the result)."""
        from app.features.wifi_switch import switch_network

        body = request.get_json(silent=True) or {}
        res = switch_network(node_id,
                             str(body.get("ssid", "")),
                             str(body.get("password", "")),
                             board=str(body.get("board", "brain")))
        return jsonify(res), (200 if res.get("ok") else 400)

    @app.route("/api/diagnose", methods=["GET"])
    @require_tenant
    def api_diagnose(claims):
        """Why isn't a part showing up? Reports board declarations, catalogue and devices, in that order."""
        from app.config import RELEASE_ID
        from app.features.device_store import list_devices
        from app.features.node_provision import PART_CATALOGUE
        from app.features.node_store import list_nodes
        from app.integrations.mqtt_ingest import get_ingest_stats

        nodes = list_nodes()
        devices = list_devices()

        report = {
            "server_release": RELEASE_ID,
            # This worker's MQTT listener (publishing uses a different client);
            # per worker, so refresh a few times.
            "mqtt_ingest": get_ingest_stats(),
            "catalogue_knows": sorted(PART_CATALOGUE),
            "nodes": [
                {
                    "node_id": n.get("node_id"),
                    "online": n.get("online"),
                    "firmware": n.get("firmware_version"),
                    "last_seen": n.get("last_seen"),
                    "declared_outputs": [o.get("id") for o in (n.get("outputs") or [])],
                    "telemetry_keys": sorted((n.get("telemetry") or {}).keys()),
                    "ip": (n.get("telemetry") or {}).get("ip"),
                    "board": (n.get("telemetry") or {}).get("board"),
                }
                for n in nodes
            ],
            "devices": [
                {"name": d.get("name"), "type": d.get("control_type")}
                for d in devices
            ],
        }

        declared = {o for n in nodes for o in
                    [x.get("id") for x in (n.get("outputs") or [])]}
        provisioned = {d.get("name") for d in devices}
        report["checks"] = {
            "declared_but_no_catalogue_entry":
                sorted(declared - set(PART_CATALOGUE)),
            "catalogue_has_but_board_never_declared":
                sorted(set(PART_CATALOGUE) - declared),
            "screen_device_exists": "sandy_screen" in provisioned,
            "camera_devices_exist":
                sorted(n for n in provisioned if n.startswith("cam_")),
        }
        return jsonify(report), 200

    @app.route("/api/devices/<name>/image", methods=["POST"])
    @require_tenant
    def api_devices_image(claims, name):
        """Send a base64 picture to a node display device (resized and chunked by screen_sender)."""
        import base64 as _b64

        from app.features.device_store import get_device
        from app.features.screen_sender import send_image

        device = get_device(name)
        if device is None:
            return _bad("not_found", code=404)

        transport = device.get("transport") or {}
        if str(transport.get("kind", "")) != "node":
            return _bad("not_a_node_device")
        node_id = str(transport.get("node_id", "")).strip()
        if not node_id:
            return _bad("bad_transport")

        body = request.get_json(silent=True) or {}
        raw_b64 = body.get("image_base64") or ""
        if not raw_b64:
            return _bad("no_image")
        # Bound the allocation before decoding.
        if len(raw_b64) > 8 * 1024 * 1024:
            return _bad("too_large")
        try:
            image_bytes = _b64.b64decode(raw_b64, validate=True)
        except Exception:  # noqa: BLE001
            return _bad("bad_base64")

        res = send_image(node_id, image_bytes)
        if not res.get("ok"):
            return _bad(res.get("error", "send_failed"), res)
        return jsonify(res), 200

    @app.route("/api/nodes/<node_id>/snapshot", methods=["POST"])
    @require_tenant
    def api_node_snapshot(claims, node_id):
        """Ask the camera for a photo: the JPEG if it lands within ~3 s, else 202 with a ticket."""
        from app.features.node_store import get_node
        from app.integrations.camera_client import (
            fetch_snapshot,
            fetch_snapshot_error,
            start_snapshot,
        )

        if get_node(node_id) is None:
            return _bad("not_found", code=404)

        body = request.get_json(silent=True) or {}
        try:
            settle_ms = int(body.get("settle_ms", 0) or 0)
        except (TypeError, ValueError):
            return _bad("bad_settle_ms")
        req_id = start_snapshot(
            node_id,
            settle_ms=settle_ms,
            flash=str(body.get("flash", "auto")),
        )
        if not req_id:
            return _bad("not_sent", code=502)

        deadline = time.time() + 3.0
        while time.time() < deadline:
            jpeg = fetch_snapshot(node_id, req_id)
            if jpeg:
                return Response(jpeg, mimetype="image/jpeg")
            failed = fetch_snapshot_error(node_id, req_id)
            if failed:
                return jsonify(failed), 502
            time.sleep(0.3)
        return jsonify({"pending": True, "req_id": req_id}), 202

    @app.route("/api/cam/upload", methods=["POST"])
    def api_cam_upload():
        """The camera posts a finished JPEG here (photos don't travel over MQTT).

        Authenticated by HMAC over node + request + timestamp (+ body hash on newer
        firmware) with a replay window. Uses the camera's own key (``X-Sandy-Kv: 2``)
        once it has one, else the shared key; right after pairing the reply carries its
        own key (features/device_keys, separate id from the robot's).
        """
        import hashlib
        import hmac as _hmac

        # Same key as the voice link.
        from app.api.voice_ws._config import _HMAC_KEY as key
        if not key:
            return _bad("auth_not_configured", code=503)

        node_id = (request.headers.get("X-Sandy-Node") or "").strip()
        req_id = (request.headers.get("X-Sandy-Req") or "").strip()
        ts = (request.headers.get("X-Sandy-Ts") or "").strip()
        sig = (request.headers.get("X-Sandy-Sig") or "").strip()
        if not (node_id and req_id and ts and sig):
            logger.warning(
                "[cam] upload rejected: missing headers "
                "(node=%s req=%s ts=%s sig=%s)",
                bool(node_id), bool(req_id), bool(ts), bool(sig))
            return _bad("missing_headers")
        # Validate ids first: they become storage keys and log lines.
        if not (_CAM_NODE_RE.fullmatch(node_id) and _CAM_REQ_RE.fullmatch(req_id)):
            logger.warning("[cam] upload rejected: malformed node/request id")
            return _bad("bad_id")
        # Size before reading the body.
        if (request.content_length or 0) > _CAM_MAX_UPLOAD_BYTES:
            logger.warning("[cam] upload rejected: %s bytes is too big",
                           request.content_length)
            return _bad("too_large", code=413)

        # Every rejection is logged with its reason; the board only sees 400.
        try:
            age = abs(time.time() * 1000 - int(ts))
        except ValueError:
            logger.warning("[cam] upload rejected: unreadable timestamp %r", ts[:32])
            return _bad("bad_ts")
        if age > 120_000:
            # Usually a board that booted with its clock at 1970, before time sync.
            logger.warning("[cam] upload rejected: timestamp is %.0f minutes off — "
                        "the board's clock is probably not synced", age / 60000)
            return _bad("stale")

        from app.features.device_keys import (
            KEY_VERSION, cam_key_id, confirm_key, get_key, issue_key,
        )
        kid = cam_key_id(node_id)
        own_key = (request.headers.get("X-Sandy-Kv") or "").strip() == str(KEY_VERSION)
        record = get_key(kid)
        if own_key:
            if record is None:
                # The camera falls back to the shared key until it's paired again.
                logger.warning("[cam] upload rejected: no key on record for %s", node_id)
                return _bad("key_unknown", code=401)
            key = record["key"]
        elif record is not None and record["state"] == "confirmed":
            logger.warning("[cam] upload rejected: shared key refused for %s — it "
                        "has its own key", node_id)
            return _bad("auth_fail", code=401)

        jpeg = request.get_data(cache=False)
        if len(jpeg) > _CAM_MAX_UPLOAD_BYTES:
            return _bad("too_large", code=413)

        # The signature covers the body hash on newer firmware; old firmware
        # (no hash) is still accepted with a warning.
        body_hash = (request.headers.get("X-Sandy-Body-Sha256") or "").strip().lower()
        if body_hash:
            if not _hmac.compare_digest(hashlib.sha256(jpeg).hexdigest(), body_hash):
                logger.warning("[cam] upload rejected: body does not match its hash")
                return _bad("auth_fail", code=401)
            signed = f"{node_id}{req_id}{ts}{body_hash}"
        else:
            logger.warning("[cam] %s signs without a body hash — old firmware", node_id)
            signed = f"{node_id}{req_id}{ts}"
        expected = _hmac.new(key, signed.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, sig):
            logger.warning(
                "[cam] upload rejected: bad signature for %s", node_id)
            return _bad("auth_fail", code=401)

        # One use per signature. Keyed with the body hash too: old firmware signs to
        # the second, so two frames in one second share a signature but not bytes.
        if not _cam_signature_fresh(sig + hashlib.sha256(jpeg).hexdigest()[:16]):
            logger.warning("[cam] upload rejected: replayed signature for %s", node_id)
            return _bad("replay", code=401)
        if own_key and record["state"] == "issued":
            confirm_key(kid)

        # JPEG magic bytes: refuse truncated or misrouted bodies here.
        if len(jpeg) < 100 or jpeg[:2] != b"\xff\xd8":
            logger.warning("[cam] upload rejected: not a jpeg (%d bytes, starts %r)",
                        len(jpeg), jpeg[:4])
            return _bad("not_a_jpeg")

        from app.integrations.camera_client import store_snapshot
        store_snapshot(node_id, req_id, jpeg)
        logger.info(
            "[cam] upload ok: %s %s (%d bytes)", node_id, req_id, len(jpeg))
        reply = {"ok": True, "bytes": len(jpeg)}
        if not own_key:
            try:
                from app.features.node_store import get_node_any_tenant
                if get_node_any_tenant(node_id):
                    fresh = issue_key(kid)   # None outside the pairing window
                    if fresh:
                        reply["device_key"] = fresh
            except Exception as exc:  # noqa: BLE001 — enrolment is extra, not a gate
                logger.warning("[cam] key issue failed for %s: %s", node_id, exc)
        return jsonify(reply), 200

    @app.route("/api/nodes/<node_id>/snapshot/<req_id>", methods=["GET"])
    @require_tenant
    def api_node_snapshot_fetch(claims, node_id, req_id):
        """Collect a photo by ticket: 200 JPEG, 202 not yet, 502 the camera said it failed, 404 not yours."""
        from app.features.node_store import get_node
        from app.integrations.camera_client import fetch_snapshot, fetch_snapshot_error

        if get_node(node_id) is None:
            return _bad("not_found", code=404)
        jpeg = fetch_snapshot(node_id, req_id)
        if jpeg:
            return Response(jpeg, mimetype="image/jpeg")
        failed = fetch_snapshot_error(node_id, req_id)
        if failed:
            return jsonify(failed), 502
        return jsonify({"pending": True, "req_id": req_id}), 202

    @app.route("/api/devices/<name>/ir-learn", methods=["POST"])
    @require_tenant
    def api_devices_ir_learn(claims, name):
        from app.features.device_store import learn_ir_button

        body = request.get_json(silent=True) or {}
        r = learn_ir_button(name, body.get("button", ""), body.get("code", ""))
        if not r.get("ok"):
            return _bad(r.get("error", "learn_failed"))
        return jsonify(r), 200

    # ── Nodes ───────────────────────────────────────────────────────────────
    @app.route("/api/nodes", methods=["GET"])
    @require_auth
    def api_nodes_list(claims):
        if _is_guest(claims):
            return jsonify({"items": [], "demo": True}), 200
        from app.features.node_store import list_nodes

        with active_user_profile_context(build_user_profile(claims)):
            return jsonify({"items": list_nodes(), "demo": False}), 200

    @app.route("/api/nodes/pair", methods=["POST"])
    @require_tenant
    def api_nodes_pair(claims):
        """Claim a robot; rate limited because the code is only four characters.

        A free robot needs proof of presence (202 + code on its screen, then /pair/confirm).
        """
        from app.api.auth_handlers import check_rate_limit
        from app.features.node_store import pair_node

        who = str(claims.get("user_id") or "") or request.remote_addr or "unknown"
        allowed, _ = check_rate_limit(who, scope="node_pair")
        if not allowed:
            return _bad("too_many_attempts", code=429)

        body = request.get_json(silent=True) or {}
        code = str(body.get("code", ""))
        from app.features.node_store import pair_precheck

        pre = pair_precheck(code)
        state = pre.get("state")
        if state == "claimed":
            # "Belongs to another account" is actionable (factory reset it).
            return _bad("already_claimed")
        if state in ("bad_code", "no_store"):
            return _bad(state)
        if state == "free" and PAIR_NEEDS_PRESENCE:
            from app.features import pair_presence

            tenant = str(claims.get("user_id") or "")
            ch = pair_presence.start(pre["node_id"], tenant)
            if not ch.get("ok"):
                return _bad(ch.get("error", "pair_failed"))
            return jsonify({"ok": True, "needs_presence": True, "node_id": pre["node_id"],
                            "sent": ch.get("sent", False),
                            "expires_in": ch.get("expires_in")}), 202
        r = pair_node(code, body.get("label", ""))
        if not r.get("ok"):
            return _bad(r.get("error", "pair_failed"))
        return jsonify(r), 200

    @app.route("/api/nodes/pair/confirm", methods=["POST"])
    @require_tenant
    def api_nodes_pair_confirm(claims):
        """Finish pairing with the six digits shown on the robot's screen."""
        from app.api.auth_handlers import check_rate_limit
        from app.features import pair_presence
        from app.features.node_store import pair_node, pair_precheck

        who = str(claims.get("user_id") or "") or request.remote_addr or "unknown"
        allowed, _ = check_rate_limit(who, scope="node_pair_confirm")
        if not allowed:
            return _bad("too_many_attempts", code=429)

        body = request.get_json(silent=True) or {}
        code = str(body.get("code", ""))
        pre = pair_precheck(code)
        if pre.get("state") == "claimed":
            return _bad("already_claimed")
        if pre.get("state") not in ("free", "ours"):
            return _bad(pre.get("state") or "bad_code")
        if pre.get("state") == "free":
            ok = pair_presence.confirm(pre["node_id"], str(claims.get("user_id") or ""),
                                       str(body.get("presence", "")))
            if not ok.get("ok"):
                return jsonify({"ok": False, "error": ok.get("error"),
                                "tries_left": ok.get("tries_left")}), 400
        r = pair_node(code, body.get("label", ""))
        if not r.get("ok"):
            return _bad(r.get("error", "pair_failed"))
        return jsonify(r), 200

    @app.route("/api/nodes/<node_id>", methods=["PATCH"])
    @require_tenant
    def api_nodes_rename(claims, node_id):
        from app.features.node_store import rename_node

        body = request.get_json(silent=True) or {}
        r = rename_node(node_id, body.get("label", ""))
        if not r.get("ok"):
            return _bad(r.get("error", "rename_failed"), code=404)
        return jsonify(r), 200

    @app.route("/api/nodes/<node_id>/ir/learn", methods=["POST"])
    @require_tenant
    def api_nodes_ir_learn_start(claims, node_id):
        """Arm IR learn mode; the ingest listener stores the captured code for /ir/last."""
        from app.features.node_store import get_node
        from app.integrations.room_device import get_room_device_client

        # Ownership: only a node this tenant paired.
        if get_node(node_id.strip()) is None:
            return _bad("not_found", code=404)
        sent = False
        try:
            topic = f"sandy/node/{node_id.strip()}/ir"
            sent = get_room_device_client().send_to_topic(topic, "learn")
        except Exception:  # noqa: BLE001
            sent = False
        return jsonify({"ok": True, "sent": sent}), 200

    @app.route("/api/nodes/<node_id>/ir/last", methods=["GET"])
    @require_tenant
    def api_nodes_ir_last(claims, node_id):
        from app.features.node_store import get_last_ir

        r = get_last_ir(node_id)
        if not r.get("ok"):
            return _bad(r.get("error", "not_found"), code=404)
        return jsonify(r), 200

    @app.route("/api/nodes/<node_id>", methods=["DELETE"])
    @require_tenant
    def api_nodes_unpair(claims, node_id):
        """Release a robot (unpair_node wipes the board first); the reply says whether the wipe reached it."""
        from app.features.node_store import unpair_node

        r = unpair_node(node_id)
        if not r.get("ok"):
            return _bad(r.get("error", "unpair_failed"), code=404)
        return jsonify(r), 200
