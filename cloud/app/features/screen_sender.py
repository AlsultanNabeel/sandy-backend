"""Send text or a picture to Sandy's display.

Pictures go as raw big-endian RGB565 (the display runs CONFIG_LV_COLOR_16_SWAP;
the board decodes nothing), chunked because 240x240 is too big for one MQTT message.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

SCREEN_W = 240
SCREEN_H = 240
IMG_BYTES = SCREEN_W * SCREEN_H * 2

# Raw bytes per chunk before base64; the firmware caps a decoded chunk at 16 KB and 64 chunks.
CHUNK_BYTES = 6 * 1024
MAX_CHUNKS = 64

# Firmware text buffer is 256 bytes incl. terminator; measured in bytes (Arabic is multi-byte).
TEXT_MAX_BYTES = 255


def _topic(node_id: str, output: str) -> str:
    return f"sandy/node/{node_id}/{output}"


def to_rgb565(image_bytes: bytes) -> bytes:
    """Centre-crop to square, resize, and convert to the panel's pixel format."""
    from PIL import Image, ImageOps  # noqa: PLC0415 — heavy, only needed here

    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)          # honour the phone's rotation
    img = img.convert("RGB")
    img = ImageOps.fit(img, (SCREEN_W, SCREEN_H), method=Image.LANCZOS,
                       centering=(0.5, 0.5))

    rgb = img.tobytes()
    out = bytearray(IMG_BYTES)
    for px in range(SCREEN_W * SCREEN_H):
        r, g, b = rgb[px * 3], rgb[px * 3 + 1], rgb[px * 3 + 2]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[px * 2] = (v >> 8) & 0xFF
        out[px * 2 + 1] = v & 0xFF
    return bytes(out)


def send_image(node_id: str, image_bytes: bytes) -> Dict[str, Any]:
    from app.integrations.room_device import get_room_device_client

    node_id = (node_id or "").strip()
    if not node_id:
        return {"ok": False, "error": "no_node"}
    if not image_bytes:
        return {"ok": False, "error": "empty"}

    try:
        raw = to_rgb565(image_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screen] could not read the image: %s", exc)
        return {"ok": False, "error": "bad_image"}

    chunks = [raw[i:i + CHUNK_BYTES] for i in range(0, len(raw), CHUNK_BYTES)]
    if len(chunks) > MAX_CHUNKS:
        return {"ok": False, "error": "too_many_chunks"}

    client = get_room_device_client()
    topic = _topic(node_id, "screen_img")
    total = len(chunks)

    # publish_service, not send_to_topic: `screen_img` is a channel, not a device.
    # Ownership is checked on the node instead.
    from app.features.node_store import get_node
    if get_node(node_id) is None:
        logger.warning("[screen] refused: %s is not a node this caller owns", node_id)
        return {"ok": False, "error": "not_yours"}

    for seq, chunk in enumerate(chunks):
        payload = f"{seq}:{total}:" + base64.b64encode(chunk).decode("ascii")
        if not client.publish_service(topic, payload):
            logger.warning("[screen] chunk %d/%d not sent — abandoning", seq, total)
            return {"ok": False, "error": "not_sent", "sent": seq}

    logger.info("[screen] image sent to %s in %d chunks", node_id, total)
    return {"ok": True, "chunks": total, "bytes": len(raw)}
