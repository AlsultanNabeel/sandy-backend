"""Move the robot onto a different Wi-Fi network, from the app.

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


# The first firmware that reads only the signed command. Older ones read
# "<ssid>\n<password>" and nothing else, so they keep getting it until they update.
SIGNED_FROM = "0.12.0"


def _reads_signed(node: Dict[str, Any]) -> bool:
    """A board that never said its version is taken as new: signed is the safe side."""
    from app.features.firmware_store import version_key

    version = str(node.get("firmware_version") or "")
    return not version or version_key(version) >= version_key(SIGNED_FROM)


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


def _payloads(node: Dict[str, Any], node_id: str,
              ssid: str, password: str) -> Optional[list]:
    """What goes on the wire, once per key the board may check it with; None with no key."""
    from app.features.node_store import signing_keys

    if not _reads_signed(node):
        return [f"{ssid}\n{password}"]
    ms = str(int(time.time() * 1000))
    keys = signing_keys(node_id)
    return [_signed_command(node_id, ssid, password, k, ms) for k in keys] or None


def switch_network(node_id: str, ssid: str, password: str,
                   board: str = "brain") -> Dict[str, Any]:
    """Ask the robot to move to `ssid`. Returns immediately. `board` is what an older app
    still sends; anything but the brain is refused, never sent to the brain instead."""
    from app.features.device_keys import KeyUnreadable
    from app.features.node_store import get_node
    from app.integrations.device_publisher import get_device_publisher

    node_id = (node_id or "").strip()
    ssid = (ssid or "").strip()
    password = password or ""

    if not node_id:
        return {"ok": False, "error": "no_node"}
    if board != "brain":
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
        payloads = _payloads(node, node_id, ssid, password)
    except KeyUnreadable:
        logger.error("[wifi] %s: its key record cannot be read", node_id)
        return {"ok": False, "error": "key_unreadable"}
    if not payloads:
        logger.warning("[wifi] no key to sign the switch of %s", node_id)
        return {"ok": False, "error": "not_sent"}

    topic = f"sandy/node/{node_id}/wifi"
    client = get_device_publisher()
    sent = [client.publish_service(topic, p) for p in payloads]
    if not any(sent):
        return {"ok": False, "error": "not_sent"}

    logger.info("[wifi] asked %s to try '%s'", node_id, ssid)
    return {"ok": True, "window_s": SWITCH_WINDOW_S, "ssid": ssid, "board": board}
