"""The room node's light arm, set up from the app: where it rests, how far it presses for on
and for off, and how long each press holds.

A service channel (`room/light_arm`), not a device: it never appears in the device list, and
nothing here touches the light's saved state, so trying a press changes neither the board's
`light` nor the device row. The board checks the same limits and keeps what it saves.

    goto       move the arm to one angle and hold it there a moment, to see where it lands
    try_on     one full press with the values given, not saved
    try_off
    save       keep the values; every press uses them from now on
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# The firmware's limits (room-node.ino, ARM_*): past them the servo hits its end stop,
# or a press too short does not reach the switch.
ANGLE_MIN, ANGLE_MAX = 10, 170
GAP_MIN = 10
HOLD_MIN_MS, HOLD_MAX_MS = 150, 1500

ACTIONS = ("goto", "try_on", "try_off", "save")


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f == int(f) else None


def arm_values(body: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """`rest,on,off,hold_ms` for the wire, or the error code."""
    rest, on, off, hold = (_int(body.get(k)) for k in ("rest", "on", "off", "hold_ms"))
    if None in (rest, on, off, hold):
        return None, "missing_values"
    if any(a < ANGLE_MIN or a > ANGLE_MAX for a in (rest, on, off)):
        return None, "angle_out_of_range"
    lo, hi = min(on, off), max(on, off)
    # Rest between the two presses and clear of both, or one press does both.
    if rest - lo < GAP_MIN or hi - rest < GAP_MIN:
        return None, "rest_not_between"
    if hold < HOLD_MIN_MS or hold > HOLD_MAX_MS:
        return None, "hold_out_of_range"
    return f"{rest},{on},{off},{hold}", None


def wire_command(body: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """The payload for `room/light_arm`, or the error code."""
    action = str(body.get("action", ""))
    if action not in ACTIONS:
        return None, "bad_action"
    if action == "goto":
        angle = _int(body.get("angle"))
        if angle is None or angle < ANGLE_MIN or angle > ANGLE_MAX:
            return None, "angle_out_of_range"
        return f"goto:{angle}", None
    values, err = arm_values(body)
    if err:
        return None, err
    if action == "save":
        return f"set:{values}", None
    return f"try:{'on' if action == 'try_on' else 'off'}:{values}", None


def command(node_id: str, body: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Send one arm command to the caller's own room node. (reply, HTTP status)"""
    from app.features.node_store import get_node
    from app.integrations.room_device import get_room_device_client

    node_id = (node_id or "").strip()
    payload, err = wire_command(body if isinstance(body, dict) else {})
    if err:
        return {"ok": False, "error": err}, 400
    # Ownership: only a node this tenant paired (scoped read).
    node = get_node(node_id)
    if node is None:
        return {"ok": False, "error": "not_found"}, 404
    if (node.get("telemetry") or {}).get("room_online") is not True:
        return {"ok": False, "error": "room_offline"}, 409
    sent = get_room_device_client().publish_service(f"sandy/node/{node_id}/room/light_arm", payload)
    if not sent:
        return {"ok": False, "error": "not_sent"}, 503
    logger.info("[room_arm] %s → %s", node_id, payload)
    return {"ok": True}, 200
