"""Sandy's body reacting to what she does: faces, melodies, lights on the owner's robot.

Best-effort: an offline robot or phone-only account must never break a feature.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _node_id() -> Optional[str]:
    """The caller's own online robot (tenant-scoped), or None."""
    from app.features.node_store import list_nodes
    for n in list_nodes() or []:
        if n.get("online"):
            return str(n.get("node_id") or "") or None
    return None


def _send(output: str, value: str) -> bool:
    node = _node_id()
    if not node:
        return False
    from app.integrations.room_device import get_room_device_client
    return bool(get_room_device_client().send_to_topic(
        f"sandy/node/{node}/{output}", value))


def express(mood: str = "", melody: str = "", led: str = "") -> None:
    """React with a face, a sound and/or a light.

    Face first (instant), light last: during a live voice session the board may
    refuse it so the privacy indicator stays visible. The one catch is here, at the edge.
    """
    try:
        if mood:
            _send("mood", mood)
        if melody:
            _send("buzzer", melody)
        if led:
            _send("led", led)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[expression] not shown (%s/%s/%s): %s", mood, melody, led, exc)


# ── Named moments: callers say what happened, this decides what it looks like ──

def celebrate() -> None:
    """Goal completed, streak kept: the biggest reaction."""
    express(mood="big_happy", melody="celebrate", led="party")


def focus_begin() -> None:
    express(mood="focused", melody="focus_start", led="breathe")


def focus_end() -> None:
    express(mood="happy", melody="focus_end", led="idle")


def notify() -> None:
    express(mood="alert", melody="notify")


def acknowledge() -> None:
    """Small and frequent (task ticked, item bought), so deliberately quiet."""
    express(mood="happy", melody="yes")


def thinking() -> None:
    express(mood="thinking", led="pulse")


def reading() -> None:
    express(mood="calm", led="candle")
