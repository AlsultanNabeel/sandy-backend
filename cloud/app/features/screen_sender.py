"""Send text or a picture to Sandy's display.

The picture path is the interesting one, and two decisions shape it.

**The board decodes nothing.** It is handed raw RGB565 pixels in exactly the
layout its panel wants — resized, converted and byte-ordered here. A JPEG
decoder on the ESP32 would cost internal RAM that the voice session needs, and
would mean a photo could fail on the one device the owner cannot attach a
debugger to. Failures belong on the server, where they can be seen.

**It arrives in pieces.** 240x240 RGB565 is 115,200 bytes and no MQTT broker
will take that in one message, so it is chunked — the same shape the camera
already uses to send snapshots in the other direction. One pattern to
understand, not two.

The byte order is not a detail: the display is configured with
`CONFIG_LV_COLOR_16_SWAP=y`, so each pixel goes out big-endian. Get it wrong and
the picture appears in convincing, entirely wrong colours — which looks like an
artistic choice rather than a bug, and is therefore the kind of mistake that
survives for weeks.
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

# Chunk size in raw bytes before base64 (which inflates by 4/3). 6 KB in becomes
# 8 KB of text — comfortably inside a broker message, and 20 chunks for a full
# frame. The firmware caps a decoded chunk at 16 KB and the transfer at 64
# chunks; both ends have to agree, so this is the number that keeps them honest.
CHUNK_BYTES = 6 * 1024
MAX_CHUNKS = 64

# The text the display can hold. The firmware's buffer is 256 bytes including
# the terminator, and Arabic is multi-byte in UTF-8 — so this is measured in
# bytes, not characters, or a short Arabic sentence would be truncated mid-letter
# by the board instead of being refused politely here.
TEXT_MAX_BYTES = 255


def _topic(node_id: str, output: str) -> str:
    return f"sandy/node/{node_id}/{output}"


def send_text(node_id: str, text: str) -> Dict[str, Any]:
    """Put a line of text on the display. Empty text takes it down."""
    from app.integrations.room_device import get_room_device_client

    node_id = (node_id or "").strip()
    if not node_id:
        return {"ok": False, "error": "no_node"}

    text = (text or "").strip()
    encoded = text.encode("utf-8")
    if len(encoded) > TEXT_MAX_BYTES:
        return {"ok": False, "error": "too_long", "max_bytes": TEXT_MAX_BYTES}

    client = get_room_device_client()
    payload = f"text:{text}" if text else "dismiss"
    ok = client.send_to_topic(_topic(node_id, "screen"), payload)
    return {"ok": bool(ok)} if ok else {"ok": False, "error": "not_sent"}


def dismiss(node_id: str) -> Dict[str, Any]:
    """Take whatever is on the display down and give the face back."""
    from app.integrations.room_device import get_room_device_client

    node_id = (node_id or "").strip()
    if not node_id:
        return {"ok": False, "error": "no_node"}
    ok = get_room_device_client().send_to_topic(_topic(node_id, "screen"), "dismiss")
    return {"ok": bool(ok)} if ok else {"ok": False, "error": "not_sent"}


def to_rgb565(image_bytes: bytes) -> bytes:
    """Any image the owner picked -> exactly what the panel draws.

    Square-cropped from the centre before resizing, so a wide photo loses its
    edges rather than being squashed. A face stretched to fit is worse than a
    face with less background.
    """
    from PIL import Image, ImageOps  # noqa: PLC0415 — heavy, only needed here

    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)          # honour the phone's rotation
    img = img.convert("RGB")
    img = ImageOps.fit(img, (SCREEN_W, SCREEN_H), method=Image.LANCZOS,
                       centering=(0.5, 0.5))

    # tobytes() rather than getdata(): one buffer instead of 57,600 tuples, and
    # getdata() is deprecated in Pillow 14.
    rgb = img.tobytes()
    out = bytearray(IMG_BYTES)
    for px in range(SCREEN_W * SCREEN_H):
        r, g, b = rgb[px * 3], rgb[px * 3 + 1], rgb[px * 3 + 2]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        # Big-endian: the display runs with LV_COLOR_16_SWAP.
        out[px * 2] = (v >> 8) & 0xFF
        out[px * 2 + 1] = v & 0xFF
    return bytes(out)


def send_image(node_id: str, image_bytes: bytes) -> Dict[str, Any]:
    """Convert, chunk and publish a picture to the display."""
    from app.integrations.room_device import get_room_device_client

    node_id = (node_id or "").strip()
    if not node_id:
        return {"ok": False, "error": "no_node"}
    if not image_bytes:
        return {"ok": False, "error": "empty"}

    try:
        raw = to_rgb565(image_bytes)
    except Exception as exc:  # noqa: BLE001 — a bad upload is the user's, not ours
        logger.warning("[screen] could not read the image: %s", exc)
        return {"ok": False, "error": "bad_image"}

    chunks = [raw[i:i + CHUNK_BYTES] for i in range(0, len(raw), CHUNK_BYTES)]
    if len(chunks) > MAX_CHUNKS:
        return {"ok": False, "error": "too_many_chunks"}

    client = get_room_device_client()
    topic = _topic(node_id, "screen_img")
    total = len(chunks)

    # Ownership is checked once, on the first chunk, by send_to_topic. If the
    # caller does not own this node the first publish fails and the rest are
    # skipped — no half-sent picture, and no per-chunk ownership lookup either.
    for seq, chunk in enumerate(chunks):
        payload = f"{seq}:{total}:" + base64.b64encode(chunk).decode("ascii")
        if not client.send_to_topic(topic, payload):
            logger.warning("[screen] chunk %d/%d not sent — abandoning", seq, total)
            return {"ok": False, "error": "not_sent", "sent": seq}

    logger.info("[screen] image sent to %s in %d chunks", node_id, total)
    return {"ok": True, "chunks": total, "bytes": len(raw)}
