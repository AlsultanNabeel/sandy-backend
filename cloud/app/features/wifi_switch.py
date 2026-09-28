"""Move a board onto a different Wi-Fi network, from the app.

Nothing is committed here: the board tries the new network and rolls back by
itself if it fails. Which network answered shows up in its next heartbeat's `ssid`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# The board rolls back after 25 s; the app waits a little longer.
SWITCH_WINDOW_S = 35

SSID_MAX = 32
PASS_MAX = 64


# Brain and camera share a node id, so the caller must say which board moves.
BOARDS = {
    "brain": "wifi",
    "camera": "cam/wifi",
}


def switch_network(node_id: str, ssid: str, password: str,
                   board: str = "brain") -> Dict[str, Any]:
    """Ask one board to move to `ssid`. Returns immediately."""
    from app.features.node_store import get_node
    from app.integrations.room_device import get_room_device_client

    node_id = (node_id or "").strip()
    ssid = (ssid or "").strip()
    password = password or ""

    if not node_id:
        return {"ok": False, "error": "no_node"}
    if board not in BOARDS:
        return {"ok": False, "error": "bad_board"}
    if not ssid:
        return {"ok": False, "error": "no_ssid"}
    if len(ssid) > SSID_MAX or len(password) > PASS_MAX:
        return {"ok": False, "error": "too_long"}
    # Newline is the wire separator; SSIDs/passwords may contain anything else.
    if "\n" in ssid or "\n" in password:
        return {"ok": False, "error": "bad_chars"}

    # Ownership check: otherwise any account could move someone's robot.
    if get_node(node_id) is None:
        logger.warning("[wifi] refused: %s is not a node this caller owns", node_id)
        return {"ok": False, "error": "not_yours"}

    topic = f"sandy/node/{node_id}/{BOARDS[board]}"
    ok = get_room_device_client().publish_service(topic, f"{ssid}\n{password}")
    if not ok:
        return {"ok": False, "error": "not_sent"}

    logger.info("[wifi] asked %s/%s to try '%s'", node_id, board, ssid)
    return {"ok": True, "window_s": SWITCH_WINDOW_S, "ssid": ssid, "board": board}
