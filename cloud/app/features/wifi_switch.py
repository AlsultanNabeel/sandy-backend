"""Move a board onto a different Wi-Fi network, from the app.

Nothing is committed here: the board tries the new network and rolls back by
itself if it fails. Which network answered shows up in its next heartbeat's `ssid`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# The brain waits 25 s for an address and 20 more for the server to answer through it,
# then rolls back; the app waits a little longer.
SWITCH_WINDOW_S = 55

# Counted in bytes, as 802.11 and the boards count them: an Arabic name is two a letter.
SSID_MAX = 32
# WPA2: an open network has none; otherwise a passphrase of 8 to 63 characters, or the
# key itself as 64 hex digits. Anything else the board refuses after the request was sent.
PASS_MIN = 8
PASS_MAX = 64
_HEX = set("0123456789abcdefABCDEF")


# Brain and camera share a node id, so the caller must say which board moves.
BOARDS = {
    "brain": "wifi",
    "camera": "cam/wifi",
}

# The first firmware of each board that reads only the signed command. Older boards read
# "<ssid>\n<password>" and nothing else, so they keep getting it until they update.
SIGNED_FROM = {
    "brain": "0.12.0",
    "camera": "0.5.0",
}


def _firmware(node: Dict[str, Any], board: str) -> str:
    if board == "camera":
        return str((node.get("telemetry") or {}).get("cam_fw") or "")
    return str(node.get("firmware_version") or "")


def _reads_signed(node: Dict[str, Any], board: str) -> bool:
    """A board that never said its version is taken as new: signed is the safe side."""
    from app.features.firmware_store import version_key

    version = _firmware(node, board)
    return not version or version_key(version) >= version_key(SIGNED_FROM[board])


def _signed_command(signer: str, ssid: str, password: str, key: bytes, ms: str) -> str:
    """``wifi:<ms>:<ssid hex>:<sealed password hex>:<hmac>``.

    The password, padded with zeros to 64 bytes, is XORed with a stream made from the key
    (HMAC over ``wifi-pass|<signer>|<ms>|0`` and ``…|1``), so the broker carries no password;
    the HMAC covers ``wifi|<signer>|<ms>|<ssid hex>|<sealed hex>``. The board refuses it
    unsigned, older than two minutes, or not newer than the last one it took."""
    stream = b"".join(hmac.new(key, f"wifi-pass|{signer}|{ms}|{i}".encode(),
                               hashlib.sha256).digest() for i in range(2))
    plain = password.encode("utf-8").ljust(PASS_MAX, b"\0")
    sealed = bytes(a ^ b for a, b in zip(plain, stream)).hex()
    ssid_hex = ssid.encode("utf-8").hex()
    mac = hmac.new(key, f"wifi|{signer}|{ms}|{ssid_hex}|{sealed}".encode(),
                   hashlib.sha256).hexdigest()
    return f"wifi:{ms}:{ssid_hex}:{sealed}:{mac}"


def _payloads(node: Dict[str, Any], node_id: str, board: str,
              ssid: str, password: str) -> Optional[list]:
    """What goes on the wire, once per key the board may check it with; None with no key."""
    from app.features.device_keys import cam_key_id
    from app.features.node_store import signing_keys

    if not _reads_signed(node, board):
        return [f"{ssid}\n{password}"]
    signer = cam_key_id(node_id) if board == "camera" else node_id
    ms = str(int(time.time() * 1000))
    keys = signing_keys(signer)
    return [_signed_command(signer, ssid, password, k, ms) for k in keys] or None


def switch_network(node_id: str, ssid: str, password: str,
                   board: str = "brain") -> Dict[str, Any]:
    """Ask one board to move to `ssid`. Returns immediately."""
    from app.features.device_keys import KeyUnreadable
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
    if len(ssid.encode("utf-8")) > SSID_MAX or len(password.encode("utf-8")) > PASS_MAX:
        return {"ok": False, "error": "too_long"}
    if password and (len(password.encode("utf-8")) < PASS_MIN
                     or (len(password.encode("utf-8")) == PASS_MAX and not set(password) <= _HEX)):
        return {"ok": False, "error": "bad_password"}
    # Newline is the older boards' separator; SSIDs/passwords may contain anything else.
    if "\n" in ssid or "\n" in password or "\0" in password:
        return {"ok": False, "error": "bad_chars"}

    # Ownership check: otherwise any account could move someone's robot.
    node = get_node(node_id)
    if node is None:
        logger.warning("[wifi] refused: %s is not a node this caller owns", node_id)
        return {"ok": False, "error": "not_yours"}

    try:
        payloads = _payloads(node, node_id, board, ssid, password)
    except KeyUnreadable:
        logger.error("[wifi] %s/%s: its key record cannot be read", node_id, board)
        return {"ok": False, "error": "key_unreadable"}
    if not payloads:
        logger.warning("[wifi] no key to sign the switch of %s/%s", node_id, board)
        return {"ok": False, "error": "not_sent"}

    topic = f"sandy/node/{node_id}/{BOARDS[board]}"
    client = get_room_device_client()
    sent = [client.publish_service(topic, p) for p in payloads]
    if not any(sent):
        return {"ok": False, "error": "not_sent"}

    logger.info("[wifi] asked %s/%s to try '%s'", node_id, board, ssid)
    return {"ok": True, "window_s": SWITCH_WINDOW_S, "ssid": ssid, "board": board}
