"""What a tool knows about the turn it runs in."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TurnCtx:
    user_id: str
    message: str = ""
    source: str = "chat"            # blocks.entries.SOURCES: chat | voice | app
    confirmed: bool = False         # set only when replaying a held action after "yes"
    image_state: Optional[Dict[str, Any]] = None
    # Things a tool made that are not for the model (image bytes).
    artifacts: Dict[str, Any] = field(default_factory=dict)


def needs_confirmation(summary: str) -> Dict[str, Any]:
    """A tool's answer when it will not act without a yes."""
    return {"ok": False, "needs_confirmation": True, "summary": summary}


def refused(reason: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "error": reason, **extra}
