"""journal tools."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def journal_add(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.journal_store import add_entry

    text = str(args.get("text", "")).strip()
    if not text:
        return {"handled": True, "reply": "شو بدك أدوّن؟"}
    if add_entry(text):
        return {"handled": True, "reply": "📔 دوّنتها."}
    return {"handled": True, "ok": False, "reply": "ما قدرت أدوّن."}


def journal_show(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.journal_store import entries_for, recent_entries

    date = str(args.get("date", "")).strip()
    items = entries_for(date) if date else recent_entries(limit=10)
    if not items:
        return {"handled": True, "reply": "ما في تدوينات 📔"}
    lines = [f"- ({x['date']}) {x['text']}" for x in items]
    return {"handled": True, "reply": "📔 اليوميات:\n" + "\n".join(lines)}


def journal_search(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.journal_store import search_entries

    q = str(args.get("query", "")).strip()
    if not q:
        return {"handled": True, "reply": "عن شو أفتش باليوميات؟"}
    items = search_entries(q)
    if not items:
        return {"handled": True, "reply": f"ما لقيت شي عن «{q}» باليوميات."}
    lines = [f"- ({x['date']}) {x['text']}" for x in items[:8]]
    return {"handled": True, "reply": f"📔 لقيت عن «{q}»:\n" + "\n".join(lines)}


# ── القراءة ──────────────────────────────────────────────────────────────────
