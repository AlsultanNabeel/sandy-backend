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

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
)


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"


def _forbidden():
    return jsonify({"error": "forbidden"}), 403


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
    @require_auth
    def api_devices_add(claims):
        if _is_guest(claims):
            return _forbidden()
        from app.features.device_store import add_device

        body = request.get_json(silent=True) or {}
        with active_user_profile_context(build_user_profile(claims)):
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
    @require_auth
    def api_devices_update(claims, name):
        if _is_guest(claims):
            return _forbidden()
        from app.features.device_store import update_device

        body = request.get_json(silent=True) or {}
        with active_user_profile_context(build_user_profile(claims)):
            r = update_device(name, **body)
        if not r.get("ok"):
            return _bad(r.get("error", "update_failed"),
                        {"allowed": r.get("allowed")} if r.get("allowed") else None)
        return jsonify(r), 200

    @app.route("/api/devices/<name>", methods=["DELETE"])
    @require_auth
    def api_devices_delete(claims, name):
        if _is_guest(claims):
            return _forbidden()
        from app.features.device_store import delete_device

        with active_user_profile_context(build_user_profile(claims)):
            r = delete_device(name)
        if not r.get("ok"):
            return _bad(r.get("error", "delete_failed"), code=404)
        return jsonify(r), 200

    @app.route("/api/devices/<name>/control", methods=["POST"])
    @require_auth
    def api_devices_control(claims, name):
        if _is_guest(claims):
            return _forbidden()
        from app.features.device_store import (
            command_payload,
            device_topic,
            get_device,
            set_state,
        )
        from app.integrations.room_device import get_room_device_client

        body = request.get_json(silent=True) or {}
        with active_user_profile_context(build_user_profile(claims)):
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

    @app.route("/api/devices/<name>/ir-learn", methods=["POST"])
    @require_auth
    def api_devices_ir_learn(claims, name):
        if _is_guest(claims):
            return _forbidden()
        from app.features.device_store import learn_ir_button

        body = request.get_json(silent=True) or {}
        with active_user_profile_context(build_user_profile(claims)):
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
    @require_auth
    def api_nodes_pair(claims):
        if _is_guest(claims):
            return _forbidden()
        from app.features.node_store import pair_node

        body = request.get_json(silent=True) or {}
        with active_user_profile_context(build_user_profile(claims)):
            r = pair_node(body.get("code", ""), body.get("label", ""))
        if not r.get("ok"):
            return _bad(r.get("error", "pair_failed"))
        return jsonify(r), 200

    @app.route("/api/nodes/<node_id>", methods=["PATCH"])
    @require_auth
    def api_nodes_rename(claims, node_id):
        if _is_guest(claims):
            return _forbidden()
        from app.features.node_store import rename_node

        body = request.get_json(silent=True) or {}
        with active_user_profile_context(build_user_profile(claims)):
            r = rename_node(node_id, body.get("label", ""))
        if not r.get("ok"):
            return _bad(r.get("error", "rename_failed"), code=404)
        return jsonify(r), 200

    @app.route("/api/nodes/<node_id>/ir/learn", methods=["POST"])
    @require_auth
    def api_nodes_ir_learn_start(claims, node_id):
        """Put a node into IR learn mode: it captures the next remote press and
        publishes the code, which the ingest listener stores. The app then polls
        /ir/last and saves it to a device button."""
        if _is_guest(claims):
            return _forbidden()
        from app.integrations.room_device import get_room_device_client

        with active_user_profile_context(build_user_profile(claims)):
            sent = False
            try:
                topic = f"sandy/node/{node_id.strip()}/ir"
                sent = get_room_device_client().send_to_topic(topic, "learn")
            except Exception:  # noqa: BLE001
                sent = False
        return jsonify({"ok": True, "sent": sent}), 200

    @app.route("/api/nodes/<node_id>/ir/last", methods=["GET"])
    @require_auth
    def api_nodes_ir_last(claims, node_id):
        if _is_guest(claims):
            return _forbidden()
        from app.features.node_store import get_last_ir

        with active_user_profile_context(build_user_profile(claims)):
            r = get_last_ir(node_id)
        if not r.get("ok"):
            return _bad(r.get("error", "not_found"), code=404)
        return jsonify(r), 200

    @app.route("/api/nodes/<node_id>", methods=["DELETE"])
    @require_auth
    def api_nodes_unpair(claims, node_id):
        if _is_guest(claims):
            return _forbidden()
        from app.features.node_store import unpair_node

        with active_user_profile_context(build_user_profile(claims)):
            r = unpair_node(node_id)
        if not r.get("ok"):
            return _bad(r.get("error", "unpair_failed"), code=404)
        return jsonify(r), 200
