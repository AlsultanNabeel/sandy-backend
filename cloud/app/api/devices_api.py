"""Control-tab API: device registry, node pairing, direct control. Guests get nothing.

  GET/POST /api/devices · PATCH/DELETE /api/devices/<name>
  POST /api/devices/<name>/control {action,value?} · /image {image_base64} · /ir-learn {button,code}
  GET /api/nodes · POST /api/nodes/pair {code,label?} · POST /api/nodes/pair/confirm {code,presence,label?}
  PATCH/DELETE /api/nodes/<node_id> · POST /api/nodes/<node_id>/wifi {ssid,password}
  POST /api/nodes/<node_id>/ir/learn · GET /api/nodes/<node_id>/ir/last
  GET /api/diagnose
"""

from __future__ import annotations

import logging

from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
)

logger = logging.getLogger(__name__)


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"


# A free robot is claimed only with the code shown on its own screen; turning
# this off means a photo of the box is enough to take someone's robot.
PAIR_NEEDS_PRESENCE = True


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
        from app.brain.tools_world import offline_line
        from app.integrations.device_publisher import get_device_publisher

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
        if device.get("board_gone"):
            # Its board said it went: the broker would take the command and drop it.
            return jsonify({"error": "device_offline",
                            "message": offline_line(device.get("label") or name)}), 409
        payload = res["payload"]
        sent = False
        try:
            sent = get_device_publisher().send_to_topic(topic, payload)
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
        }
        from app.api.metering import is_owner_account
        if is_owner_account(str(claims.get("user_id") or "")):
            # The project owner's own work, for every customer's released board.
            from app.features.broker_creds import to_revoke
            report["broker_logins_to_revoke"] = to_revoke()
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
        if state == "one_robot":
            # Before any code goes to its face: nothing to type for a robot that cannot pair.
            return _bad("one_robot", code=409)
        if state in ("bad_code", "no_store"):
            return _bad(state)
        if state == "free" and PAIR_NEEDS_PRESENCE:
            from app.features import pair_presence

            tenant = str(claims.get("user_id") or "")
            ch = pair_presence.start(pre["node_id"], tenant)
            if not ch.get("ok"):
                error = ch.get("error", "pair_failed")
                return _bad(error, code=409 if error == "not_connected" else 400)
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
        if pre.get("state") == "one_robot":
            return _bad("one_robot", code=409)
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
        from app.integrations.device_publisher import get_device_publisher

        # Ownership: only a node this tenant paired.
        if get_node(node_id.strip()) is None:
            return _bad("not_found", code=404)
        sent = False
        try:
            topic = f"sandy/node/{node_id.strip()}/ir"
            sent = get_device_publisher().send_to_topic(topic, "learn")
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
            # A release that stopped halfway is the server's, and asking again finishes it.
            return _bad(r.get("error", "unpair_failed"),
                        code=503 if r.get("error") == "release_failed" else 404)
        return jsonify(r), 200
