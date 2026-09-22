"""Web API for the Control tab: device registry + node pairing + direct control.

Same per-user pattern as life_api: guests are blocked from this surface entirely
(device control is real-hardware, owner/real-user only); every signed-in user acts
inside ``active_user_profile_context`` so the registry is scoped to their tenant.

Endpoints:
  GET    /api/devices                     list devices
  POST   /api/devices                     add  {name,label,control_type,transport,room?,meta?}
  PATCH  /api/devices/<name>              update {label?,room?,control_type?,transport?,meta?}
  DELETE /api/devices/<name>              delete
  POST   /api/devices/<name>/control      {action,value?}  -> actuate
  POST   /api/devices/<name>/image        {image_base64}   -> picture to a display
  POST   /api/devices/<name>/ir-learn     {button,code}    -> store a learned IR code
  GET    /api/nodes                       list paired nodes
  POST   /api/nodes/pair                  {code,label?}    -> pair (or start proof of presence)
  POST   /api/nodes/pair/confirm          {code,presence,label?} -> finish with the code on her face
  PATCH  /api/nodes/<node_id>             {label}
  DELETE /api/nodes/<node_id>             unpair (wipes the board first)
  POST   /api/nodes/<node_id>/wifi        {ssid,password,board?} -> move to a network
  POST   /api/nodes/<node_id>/snapshot    take a photo (JPEG, or 202 + ticket)
  GET    /api/nodes/<node_id>/snapshot/<req_id>  collect a photo by ticket
  POST   /api/nodes/<node_id>/ir/learn    arm IR learn mode
  GET    /api/nodes/<node_id>/ir/last     last captured IR code
  POST   /api/cam/upload                  camera posts a JPEG (HMAC, no session)
  GET    /api/diagnose                    board / catalogue / device report
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
# A free robot is claimed only with the code she shows on her own screen
# (features/pair_presence). A constant, not a switch: turning it off means a
# photo of the box is enough to take somebody's robot.
PAIR_NEEDS_PRESENCE = True
_CAM_REQ_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
_CAM_MAX_UPLOAD_BYTES = 512 * 1024
_CAM_NONCES = "cam_upload_nonces"


def _cam_signature_fresh(sig: str) -> bool:
    """True the first time a signature is seen within the replay window.

    In the database, not in memory: two workers each keeping their own set
    would let a replay through on the one that has not seen it. A database
    that is down does not stop uploads — the timestamp window still holds.
    """
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
        # Only the fields `update_device` patches. Spreading the raw body let a
        # `name` key collide with the positional argument — a TypeError, a 500.
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
        """Move one board onto a different network.

        Returns as soon as the request is sent, not when it succeeds — the board
        needs up to twenty-five seconds to try and, if it must, come back. The
        answer arrives in its next heartbeat, where `ssid` says which network
        actually answered.
        """
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
        """One request that answers "why is this not showing up?".

        Built after an afternoon of guessing. Every symptom — no text field, no
        camera, no address — had the same three possible causes, and from
        outside there was no way to tell which: the board never declared the
        part, the server has an old catalogue, or the app is stale. Each fix was
        a guess, and a wrong guess costs a deploy, a flash and a rebuild.

        So this reports all three layers at once, in the order they have to
        succeed. Read it top to bottom and the first line that disagrees with
        the next one is the answer.
        """
        from app.config import RELEASE_ID
        from app.features.device_store import list_devices
        from app.features.node_provision import PART_CATALOGUE
        from app.features.node_store import list_nodes
        from app.integrations.mqtt_ingest import get_ingest_stats

        nodes = list_nodes()
        devices = list_devices()

        report = {
            "server_release": RELEASE_ID,
            # **What this worker's MQTT listener has heard.**
            #
            # Publishing and listening are two different clients, so every
            # outbound success — a flash that lights, a 200 on control — says
            # nothing at all about whether we can hear the robot answer. That
            # asymmetry is why a camera could log a perfect capture while the
            # server reported no chunks, with no layer contradicting itself.
            #
            # Read `cam_snapshot` against `cam_status`. Both climbing means the
            # link is fine and the bug is above it. `cam_status` climbing while
            # `cam_snapshot` stays at zero means that one subscription is not
            # being delivered — check `granted_qos` for a 128. Both at zero
            # means this worker is not listening at all, and any request the
            # load balancer sends here will wait fifteen seconds for nothing.
            #
            # Note it describes ONE worker: refresh a few times, gunicorn runs
            # two and they do not share memory.
            "mqtt_ingest": get_ingest_stats(),
            "catalogue_knows": sorted(PART_CATALOGUE),
            "nodes": [
                {
                    "node_id": n.get("node_id"),
                    "online": n.get("online"),
                    "firmware": n.get("firmware_version"),
                    "last_seen": n.get("last_seen"),
                    # What the hardware itself says it has. If a part is missing
                    # here, no amount of server or app work will show it.
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

        # The three questions worth answering before anyone opens the app.
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
        """Send a picture to a display device.

        Separate from /control because a picture is not a command. Control takes
        a short string and publishes it; this takes an upload, resizes it,
        converts it to the panel's exact pixel format and publishes it across
        twenty MQTT messages. Forcing that through the same endpoint would mean
        one route that sometimes accepts JSON and sometimes a file.

        Base64 in the JSON body rather than multipart: the app already speaks
        JSON to every other endpoint, and a photo at this size is small enough
        that the 33% overhead costs less than a second code path would.
        """
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
        # 8 MB of base64 before decoding. A phone photo is well under this; the
        # cap is here so a malformed or hostile body cannot make the server
        # allocate without bound before it has looked at anything.
        if len(raw_b64) > 8 * 1024 * 1024:
            return _bad("too_large")
        try:
            image_bytes = _b64.b64decode(raw_b64, validate=True)
        except Exception:  # noqa: BLE001 — a bad upload is input, not a fault
            return _bad("bad_base64")

        res = send_image(node_id, image_bytes)
        if not res.get("ok"):
            return _bad(res.get("error", "send_failed"), res)
        return jsonify(res), 200

    @app.route("/api/nodes/<node_id>/snapshot", methods=["POST"])
    @require_tenant
    def api_node_snapshot(claims, node_id):
        """Ask the camera for one photo and hand it back as JPEG.

        This exists because a "take a photo" button with nowhere to look is not
        a feature. The command half was built first and the picture came back
        over MQTT chunks into a pending slot that nobody was waiting on, and was
        swept away — a button that worked perfectly and showed nothing.

        Blocks for up to fifteen seconds, which is a lot for a request thread
        and is why the timeout is short and the camera rate-limits itself: the
        alternative is polling, and polling for a photo somebody just asked for
        is more machinery than the wait is worth.
        """
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

        # A short grace period, because the common case is fast and a round trip
        # the caller does not need is still a round trip. Deliberately short: it
        # is an optimisation, not the mechanism. When it misses, the ticket is
        # the answer — not an error.
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
        """The camera posts a finished JPEG here. One request, one image.

        **This replaces sending photographs through the message broker.**

        MQTT is a control protocol: small messages, fire and forget, no
        acknowledgement at the quality level a board like this can publish. A
        photograph is none of those things, so every version of the broker route
        needed machinery to survive it — base64 (a third bigger), chunking,
        sequence numbers, reassembly, an inbox, tickets, timeouts, retries — and
        it still lost images, because a dropped chunk is silent by design.

        The measurement that ended the argument: heartbeats (500 bytes) always
        arrived, image chunks (1400 bytes) never did, same board, same second,
        same connection. Rather than keep shrinking the chunks until they slipped
        under whatever limit was being hit, the photo now travels over the
        protocol built for exactly this — where a failed transfer is an error,
        not silence.

        The broker keeps the job it is good at: carrying "take a photo".

        Authenticated by HMAC over node + request + timestamp — no session, no
        account, and a replay window so a captured upload cannot be repeated
        later. The key is the camera's own (``X-Sandy-Kv: 2``) once it has one;
        until then the shared key, and in the minutes after pairing the reply
        carries the camera's own key — the same enrolment as the voice link
        (features/device_keys), under a separate id so the camera and the robot
        never share a key.
        """
        import hashlib
        import hmac as _hmac

        # من `voice_ws._config` مش من البيئة مباشرة: نفس المفتاح ونفس القراءة.
        # مفتاحان بمكانين بيفترقوا يومًا ما، وساعتها بيصير الصوت شغّالًا والرفع
        # مرفوضًا بلا سبب ظاهر.
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
        # الشكل قبل أي إشي تاني: المعرّفات بتنحفظ مفاتيحًا بالصندوق وبتنكتب
        # بالسجل، ومعرّف بطول كيلو أو فيه رموز بيوصل للاتنين.
        if not (_CAM_NODE_RE.fullmatch(node_id) and _CAM_REQ_RE.fullmatch(req_id)):
            logger.warning("[cam] upload rejected: malformed node/request id")
            return _bad("bad_id")
        # والحجم قبل ما نقرا الجسم: صورة هالمستشعر عشرات الكيلوبايت، وبلا سقف
        # أي حدا معه المفتاح المشترك بيقدر يبعت ميغات ويحجز خيط الخادم.
        if (request.content_length or 0) > _CAM_MAX_UPLOAD_BYTES:
            logger.warning("[cam] upload rejected: %s bytes is too big",
                           request.content_length)
            return _bad("too_large", code=413)

        # كل رفض بينكتب بالسجل مع سببه.
        #
        # اللوح بيشوف `400 Bad Request` وبس — والأربع مئة عندها أربعة أسباب
        # مختلفة تمامًا (ترويسة ناقصة، وقت غلط، وقت قديم، مش صورة). بدون هالسطر،
        # اللوح بيقول «انرفض» والخادم بيسكت، والفرق بينهن يوم تشخيص.
        try:
            age = abs(time.time() * 1000 - int(ts))
        except ValueError:
            logger.warning("[cam] upload rejected: unreadable timestamp %r", ts[:32])
            return _bad("bad_ts")
        if age > 120_000:
            # السبب الأشيع بفارق كبير: اللوح بيقلع وساعته سنة سبعين، فأول رفع
            # قبل مزامنة الوقت بيبيّن عمره خمسة وخمسين سنة.
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
                # Un-paired, or the key was never recorded: the camera drops its
                # key and signs with the shared one until it is paired again.
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

        # **التوقيع بيغطّي الصورة نفسها.** كان بيغطّي المعرّف والوقت بس، فأي
        # حدا بيلقط رفعة ع الطريق كان بيقدر يبدّل الصورة ويبعتها بنفس التوقيع
        # خلال الدقيقتين. البرنامج الجديد بيبعت بصمة الجسم ضمن الموقَّع؛ القديم
        # (بلا بصمة) لسا مقبول لحدّ ما تنحرق كل الكاميرات، وبينكتب تحذير.
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

        # **مرّة وحدة لكل توقيع.** نافذة الدقيقتين كانت بتسمح بإعادة نفس الرفعة
        # الملقوطة قدّ ما بدّك. البصمة بتنحفظ لحدّ ما تطلع من النافذة.
        # المفتاح = التوقيع + بصمة الجسم: البرنامج القديم ما بيوقّع الجسم ووقته
        # بدقّة الثانية، فإطارين بنفس الثانية إلهم نفس التوقيع وصورتين مختلفتين
        # — مش إعادة. الإعادة هي نفس التوقيع ع نفس البايتات.
        if not _cam_signature_fresh(sig + hashlib.sha256(jpeg).hexdigest()[:16]):
            logger.warning("[cam] upload rejected: replayed signature for %s", node_id)
            return _bad("replay", code=401)
        if own_key and record["state"] == "issued":
            confirm_key(kid)

        # A JPEG starts FF D8. Checking it here means a truncated or misrouted
        # body is refused at the door rather than stored and served as a broken
        # image later, which is far harder to trace back to this moment.
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
        """Collect a photo by ticket. 202 means not yet, 404 means never.

        Split from the POST because taking a photo and having a photo are two
        different events separated by an amount of time nobody can predict — the
        board answers in a second when idle and in twenty when it is busy. Every
        version of this that tried to hide that gap inside one request either
        threw away photos that arrived late or held a worker thread hostage
        waiting for them.
        """
        from app.features.node_store import get_node
        from app.integrations.camera_client import fetch_snapshot, fetch_snapshot_error

        if get_node(node_id) is None:
            return _bad("not_found", code=404)
        jpeg = fetch_snapshot(node_id, req_id)
        if jpeg:
            return Response(jpeg, mimetype="image/jpeg")
        # الكاميرا قالت إنّ الصورة مش جاية — ليش، بكلام بيفهمه صاحبها، بدل
        # أربعين ثانية انتظار و«ما في صورة».
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
        """Claim a robot. Rate limited, because the code is short.

        A pairing code is four characters — ten thousand possibilities, which a
        script exhausts in minutes. Claim-once (enforced in `pair_node`) means a
        guessed code only wins if it belongs to a robot nobody has claimed yet;
        this limit is what stops someone sweeping the whole space looking for
        one.
        """
        from app.api.auth_handlers import check_rate_limit
        from app.features.node_store import pair_node

        who = str(claims.get("user_id") or "") or request.remote_addr or "unknown"
        allowed, _ = check_rate_limit(who, scope="node_pair")
        if not allowed:
            return _bad("too_many_attempts", code=429)

        body = request.get_json(silent=True) or {}
        code = str(body.get("code", ""))
        # **The printed code starts pairing; it no longer finishes it.** A free
        # robot answers with a code on her own face (features/pair_presence),
        # and /pair/confirm takes it. Re-pairing your own robot needs no proof.
        from app.features.node_store import pair_precheck

        pre = pair_precheck(code)
        state = pre.get("state")
        if state == "claimed":
            # Its own code, not a generic failure: "this robot belongs to another
            # account" is a sentence the owner can act on (factory reset it).
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
        """Put a node into IR learn mode: it captures the next remote press and
        publishes the code, which the ingest listener stores. The app then polls
        /ir/last and saves it to a device button."""
        from app.features.node_store import get_node
        from app.integrations.room_device import get_room_device_client

        # Ownership: only put a node THIS tenant paired into learn mode,
        # else any user could drive any node's IR by guessing its id.
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
        """Release a robot — for selling it, or handing it on.

        **Two halves, and the order is the whole trick.**

        The server releasing its claim is not enough: the board still holds the
        seller's Wi-Fi name and password in its own memory, so the buyer powers
        it on and it quietly tries to join a network in someone else's house.
        A reset that leaves that behind is not a reset.

        So the wipe goes out **first**, while we can still address the board —
        the publish path checks that the caller owns the node, and one line
        later they will not. Unpairing first would make the robot unreachable by
        the only person entitled to erase it.

        If the board is offline the unpair still happens: the account must not
        be stuck owning hardware it no longer has. The reply says which half
        succeeded, because "sold it while it was unplugged" and "wiped it
        properly" are different states and the owner should know which one he is
        in — the board will need a manual reset before the buyer can pair it.
        """
        # The wipe lives in `unpair_node` now, ahead of the release and inside
        # the same function, because deleting an account releases nodes by
        # calling it directly and was skipping this half entirely.
        from app.features.node_store import unpair_node

        r = unpair_node(node_id)
        if not r.get("ok"):
            return _bad(r.get("error", "unpair_failed"), code=404)
        return jsonify(r), 200
