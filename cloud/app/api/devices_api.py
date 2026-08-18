"""Web API for the Control tab: device registry + node pairing + direct control.

Same per-user pattern as life_api: guests are blocked from this surface entirely
(device control is real-hardware, owner/real-user only); every signed-in user acts
inside ``active_user_profile_context`` so the registry is scoped to their tenant.

Endpoints:
  GET    /api/devices                     list devices
  POST   /api/devices                     add  {name,label,control_type,transport,room?,meta?}
  PATCH  /api/devices/<name>              update {label?,room?,control_type?,transport?,meta?}
  DELETE /api/devices/<name>             delete
  POST   /api/devices/<name>/control      {action,value?}  -> actuate
  POST   /api/devices/<name>/ir-learn     {button,code}    -> store a learned IR code
  GET    /api/nodes                       list paired nodes
  POST   /api/nodes/pair                  {code,label?}    -> pair a node to this tenant
  PATCH  /api/nodes/<node_id>            {label}
  DELETE /api/nodes/<node_id>           unpair
"""

from __future__ import annotations

import time

from flask import Response, jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
)


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"


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

        body = request.get_json(silent=True) or {}
        r = update_device(name, **body)
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
        from app.integrations.camera_client import fetch_snapshot, start_snapshot

        if get_node(node_id) is None:
            return _bad("not_found", code=404)

        body = request.get_json(silent=True) or {}
        req_id = start_snapshot(
            node_id,
            settle_ms=int(body.get("settle_ms", 0) or 0),
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
            time.sleep(0.3)
        return jsonify({"pending": True, "req_id": req_id}), 202

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
        from app.integrations.camera_client import fetch_snapshot

        if get_node(node_id) is None:
            return _bad("not_found", code=404)
        jpeg = fetch_snapshot(node_id, req_id)
        if jpeg:
            return Response(jpeg, mimetype="image/jpeg")
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
        from app.features.node_store import pair_node

        body = request.get_json(silent=True) or {}
        r = pair_node(body.get("code", ""), body.get("label", ""))
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
        from app.features.node_store import unpair_node

        r = unpair_node(node_id)
        if not r.get("ok"):
            return _bad(r.get("error", "unpair_failed"), code=404)
        return jsonify(r), 200
