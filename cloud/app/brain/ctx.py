"""What a tool knows about the turn it runs in."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TurnCtx:
    user_id: str
    message: str = ""
    # The conversation's memory thread.
    thread_id: str = ""
    # The change group this turn's writes are kept under (`blocks.changes`), for undo.
    turn_id: str = ""
    source: str = "chat"            # blocks.entries.SOURCES: chat | voice | app
    confirmed: bool = False         # set only when replaying a held action after "yes"
    # On that replay, the rows the question named: the yes acts on these, never a new search.
    held_ids: Optional[List[str]] = None
    image_state: Optional[Dict[str, Any]] = None
    # Things a tool made that are not for the model (image bytes).
    artifacts: Dict[str, Any] = field(default_factory=dict)
    # Every tool call of the turn and its result, in order (`tools.execute`), and the names
    # of those that worked: what the reply may say was done (`honesty`).
    results: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    worked: List[str] = field(default_factory=list)


def needs_confirmation(summary: str, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """A tool's answer when it will not act without a yes; ``ids`` are the rows it names."""
    out: Dict[str, Any] = {"ok": False, "needs_confirmation": True, "summary": summary}
    if ids:
        out["ids"] = ids
    return out


def refused(reason: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "error": reason, **extra}
