"""Move a board onto a different Wi-Fi network, from the app.

**The danger this module is shaped around:** the only way to reach a board is
over the network it is on. Send it a wrong password and it drops off, and with it
goes the channel you would use to say "go back". The result is a cable and a
reflash — for a typo.

So nothing here commits anything. The board tries the new network, and if it does
not come up within its own window it returns to the old one by itself
(`wifi_sandy_switch` in the firmware). This side only sends and then watches the
heartbeat to see which network answered.

That is also why there is no "success" reply to wait for: a board that succeeded
reports the new SSID in its next heartbeat, and a board that failed reports the
old one. The truth is already in the data; a separate confirmation message would
be a second source for the same fact, and the two would eventually disagree.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# The board allows itself 25 s to associate before rolling back. The app should
# wait a little longer than that before deciding, hence one number, here, that
# both the API and the UI copy read.
SWITCH_WINDOW_S = 35

SSID_MAX = 32
PASS_MAX = 64


# القنوات: أي لوح تحت نفس معرّف الوحدة إله فرعه.
#
# الدماغ والكاميرا بيشاركوا معرّف الوحدة بالتصميم — الكاميرا جزء من ساندي مش
# صندوق تاني — فالمقصود مش «أي وحدة» بل «أي لوح جوّا الوحدة». وهاد لازم يكون
# صريح: «انقل ساندي» جملة ناقصة لمّا يكون فيها لوحان ع شبكتين.
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
    # A newline is the separator on the wire, so it cannot appear in either
    # field. Everything else can: network names and passwords are full of
    # colons, commas and quotes, which is exactly why none of those was chosen.
    if "\n" in ssid or "\n" in password:
        return {"ok": False, "error": "bad_chars"}

    # Ownership, before anything leaves the server. Without this any signed-in
    # account could move somebody else's robot onto a network they control.
    if get_node(node_id) is None:
        logger.warning("[wifi] refused: %s is not a node this caller owns", node_id)
        return {"ok": False, "error": "not_yours"}

    topic = f"sandy/node/{node_id}/{BOARDS[board]}"
    ok = get_room_device_client().publish_service(topic, f"{ssid}\n{password}")
    if not ok:
        return {"ok": False, "error": "not_sent"}

    logger.info("[wifi] asked %s/%s to try '%s'", node_id, board, ssid)
    return {"ok": True, "window_s": SWITCH_WINDOW_S, "ssid": ssid, "board": board}
