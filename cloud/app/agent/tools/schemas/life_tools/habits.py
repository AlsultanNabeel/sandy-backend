"""habits tools."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def habit_add(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.habits_store import add_habit

    name = str(args.get("name", "")).strip()
    if not name:
        return {"handled": True, "reply": "شو اسم العادة؟"}
    if add_habit(name):
        return {"handled": True, "reply": f"💪 سجلت عادة «{name}» — منبلش من اليوم!"}
    return {"handled": True, "reply": "هالعادة موجودة أصلاً أو الاسم فاضي."}


def habit_checkin(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.habits_store import checkin

    r = checkin(str(args.get("name", "")))
    if not r.get("ok"):
        return {"handled": True, "reply": "ما لقيت هالعادة — بدك أضيفها؟"}
    streak = r.get("streak", 1)
    if r.get("already"):
        return {"handled": True, "reply": f"مسجلة اليوم أصلاً ✅ — سلسلتك {streak} يوم 🔥"}
    cheer = " 🔥🔥" if streak >= 7 else " 🔥" if streak >= 3 else ""
    return {"handled": True, "reply": f"✅ «{r['name']}» — سلسلتك صارت {streak} يوم{cheer}"}


def habit_list(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.habits_store import list_habits

    habits = list_habits()
    if not habits:
        return {"handled": True, "reply": "ما في عادات مسجلة — قلّي «ضيفي عادة ...» ومنبدأ 💪"}
    lines = []
    for h in habits:
        mark = "✅" if h["done_today"] else "⬜"
        lines.append(f"{mark} {h['name']} — سلسلة {h['streak']} يوم")
    return {"handled": True, "reply": "💪 عاداتك:\n" + "\n".join(lines)}


# ── المصاريف ─────────────────────────────────────────────────────────────────
