"""Shared deterministic guards for command execution.

One canonical definition of the destructive-tool set, imported by both the text
router (`agents/fc_router.py`, Track 1.2) and the voice path (`api/voice_ws.py`,
Track 4.2) so the two never drift.
"""

from __future__ import annotations

# Irreversible data loss or real-world physical action. A low-confidence pick
# of one of these (text path) or any voice-issued call (voice path) is gated
# behind an explicit confirmation instead of being executed. Reversible ops
# (task_complete has task_uncomplete; focus_stop is harmless) are intentionally
# NOT here.
DESTRUCTIVE_TOOLS = frozenset({
    "task_delete",
    "reminder_delete",
    "delete_photo",
    "brainstorm_delete",
})

# Deliberately NOT above, and it matters:
#
#   device_control, scene_apply, shopping_remove
#
# Turning on a lamp is not destruction. Neither is a camera flash, a light
# effect, or a scene — every one of them is undone by saying the opposite, and
# the undo takes the same half second the action did. Putting them behind a
# spoken confirmation cost a whole extra model round trip to reach a result that
# a second sentence could have reversed anyway, so "turn on the flash" became
# "are you sure?" — then the light. The owner asked why, and he was right to.
#
# shopping_remove takes one line off a shopping list. Adding it back is one
# sentence.
#
# What is left is the set that actually loses something you cannot get back.

