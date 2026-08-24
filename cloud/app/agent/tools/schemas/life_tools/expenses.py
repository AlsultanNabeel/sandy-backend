"""expenses tools."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def expense_add(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.expenses_store import add_expense

    try:
        amount = float(args.get("amount", 0))
    except Exception:
        amount = 0
    if amount <= 0:
        return {"handled": True, "reply": "قديش المبلغ؟"}
    note = str(args.get("note", "")).strip()
    category = str(args.get("category", "")).strip()
    if add_expense(amount, note=note, category=category):
        label = note or category or ""
        return {"handled": True, "reply": f"💸 سجلت {amount:g}" + (f" — {label}" if label else "")}
    return {"handled": True, "ok": False, "reply": "ما قدرت أسجل المصروف."}


def expense_summary(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.expenses_store import month_summary

    days = int(args.get("days", 30) or 30)
    s = month_summary(days=days)
    if s["count"] == 0:
        return {"handled": True, "reply": "ما في مصاريف مسجلة بهالفترة 💸"}
    lines = [f"💸 مصاريف آخر {days} يوم: {s['total']:g} ({s['count']} عملية)"]
    for cat, total in list(s["by_category"].items())[:6]:
        lines.append(f"- {cat}: {total:g}")
    return {"handled": True, "reply": "\n".join(lines)}


# ── اليوميات ─────────────────────────────────────────────────────────────────
