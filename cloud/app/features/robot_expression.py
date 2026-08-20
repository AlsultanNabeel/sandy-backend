"""The bridge between what Sandy does and what Sandy shows.

Sandy has two halves that were never introduced. The **life** half — tasks,
focus, goals, habits, reminders — writes to a database and returns a sentence.
The **body** half — twenty-five faces, fourteen melodies, fifteen light effects —
sits on the board waiting for someone to call it.

Nobody ever did. Finishing a goal she had tracked for a month produced the word
"مبروك" and absolute silence, while `MOOD_BIG_HAPPY`, `MELODY_CELEBRATE` and
`LED_FX_PARTY` were all implemented, tested, and idle two metres away.

That is not a missing feature. It is two finished features that were never
wired together, and this module is the wire.

**Every call here is best-effort and silent on failure.** A robot that is
unplugged, asleep or on another network must never stop a reminder from being
saved. The expression is the celebration, not the achievement.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _node_id() -> Optional[str]:
    """The caller's own robot, or None if they have none.

    Tenant-scoped: `list_nodes` reads inside the active profile, so this can only
    ever return a robot the caller actually owns. A user with no hardware gets
    None and every function here becomes a no-op — which is the correct
    behaviour for a phone-only account, not an error.
    """
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
    """React: a face, a sound, a light. Any of them optional.

    Order matters and is not cosmetic. The face changes first because it is
    instant and the melody takes a second to play; doing it the other way round
    reads as a delayed reaction. The light goes last because the board may
    refuse it — during a live voice session the privacy indicator wins, and it
    should: a celebration must not be able to hide the fact that the microphone
    is on.

    **One catch, at the edge, and this is the edge.** Everything below it is
    optional hardware: an unplugged robot, a phone-only account, a board on
    another network, a broker that is briefly away. None of them are errors and
    none of them may reach the caller — losing a saved goal because a light
    failed would be a far worse bug than the silence it replaced.
    """
    try:
        if mood:
            _send("mood", mood)
        if melody:
            _send("buzzer", melody)
        if led:
            _send("led", led)
    except Exception as exc:  # noqa: BLE001 — the celebration is not the achievement
        logger.debug("[expression] not shown (%s/%s/%s): %s", mood, melody, led, exc)


# ── The moments worth reacting to ────────────────────────────────────────────
#
# Named for the event, not for the parts. A caller should say "she finished a
# goal", not pick a face — otherwise every feature invents its own idea of what
# celebrating looks like, and she stops having one personality.

def celebrate() -> None:
    """A goal completed, a habit streak kept. The biggest reaction she has."""
    express(mood="big_happy", melody="celebrate", led="party")


def focus_begin() -> None:
    """A focus session starting: the face settles, the light calms."""
    express(mood="focused", melody="focus_start", led="breathe")


def focus_break() -> None:
    express(mood="calm", melody="focus_break")


def focus_end() -> None:
    express(mood="happy", melody="focus_end", led="idle")


def notify() -> None:
    """A reminder coming due — the one case where she interrupts you."""
    express(mood="alert", melody="notify")


def acknowledge() -> None:
    """Small and frequent: a task ticked, an item bought, a habit logged.

    Deliberately quiet. A full celebration for every shopping item would make
    the celebration meaningless — and make her exhausting to live with.
    """
    express(mood="happy", melody="yes")


def thinking() -> None:
    """A brainstorm opening: she looks like she is thinking, because she is."""
    express(mood="thinking", led="pulse")


def reading() -> None:
    express(mood="calm", led="candle")
