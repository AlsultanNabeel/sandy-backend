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
    "shopping_remove",
    "device_control",
    "scene_apply",
})
