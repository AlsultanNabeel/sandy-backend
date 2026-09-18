"""#3 — Goal Tracking: تتبع أهداف المستخدم.

Sandy تحفظ الأهداف، تتابع تقدمها، وتذكّر بها استباقياً.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext

from app.utils.tenant_db import scoped
from app.utils.user_profiles import current_user_id

logger = logging.getLogger(__name__)

_COLL = "sandy_goals"


def _goals_db(ctx: "DispatchContext"):
    """Tenant-scoped handle (``chat_id`` is the tenant field); None without a
    tenant, so a turn with no signed-in user can never write a shared bucket."""
    return scoped(ctx.mongo_db, _COLL, field="chat_id")


def goal_set(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    """يحفظ هدفاً جديداً."""
    text = str(args.get("goal") or args.get("text") or "").strip()
    if not text:
        return {"handled": True, "reply": "شو الهدف اللي تبي تحققه؟"}

    coll = _goals_db(ctx)
    if coll is None:
        return {"handled": True, "ok": False, "reply": "ما قدرت أوصل للأهداف."}
    deadline = str(args.get("deadline") or "").strip() or None

    coll.insert_one({
        "user_id": str(current_user_id() or ""),
        "text": text,
        "deadline": deadline,
        "status": "active",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    deadline_str = f" (الموعد: {deadline})" if deadline else ""
    return {"handled": True, "reply": f"سجّلت هدفك: {text}{deadline_str} 🎯\nبتابعك عليه!"}


def goal_list(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    """يعرض الأهداف النشطة."""
    coll = _goals_db(ctx)
    if coll is None:
        return {"handled": True, "reply": "ما عندي أهداف محفوظة بعد."}

    status_filter = str(args.get("status") or "active")

    docs = list(coll.find(
        {"status": status_filter},
        {"_id": 1, "text": 1, "deadline": 1, "status": 1},
        sort=[("created_at", 1)],
        limit=10,
    ))

    if not docs:
        label = "مكتملة" if status_filter == "done" else "نشطة"
        return {"handled": True, "reply": f"ما في أهداف {label} حالياً."}

    lines = []
    for i, d in enumerate(docs, 1):
        deadline = f" ← {d['deadline']}" if d.get("deadline") else ""
        lines.append(f"{i}. {d['text']}{deadline}")

    header = "🎯 *أهدافك النشطة:*\n" if status_filter == "active" else "✅ *أهدافك المكتملة:*\n"
    return {"handled": True, "reply": header + "\n".join(lines)}


def goal_done(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    """يُكمّل هدفاً."""
    coll = _goals_db(ctx)
    if coll is None:
        return {"handled": True, "ok": False, "reply": "ما قدرت أوصل للأهداف."}

    goal_text = str(args.get("goal") or args.get("text") or "").strip()

    if not goal_text:
        return {"handled": True, "reply": "أي هدف خلصت منه؟"}

    result = coll.find_one_and_update(
        # Escaped: the user's words are a substring, not a pattern ("(" would
        # raise, ".*" would complete whichever goal came first).
        {"status": "active", "text": {"$regex": re.escape(goal_text[:50]), "$options": "i"}},
        {"$set": {"status": "done", "updated_at": datetime.now(timezone.utc)}},
    )

    if result:
        # **تحتفل فعلًا، مش بتكتب «مبروك».**
        #
        # هدف تابعته شهر كان بيخلص بكلمة ع الشاشة وسكوت تام — بينما وشّ الفرح
        # الكبير ونغمة الاحتفال وإضاءة الحفلة كلهن مبرمجين وشغّالين ع بعد متر.
        from app.features.robot_expression import celebrate
        celebrate()
        return {"handled": True, "reply": f"🎉 يييي! خلصت من هدف: *{result['text']}*\nأنا فخورة فيك!"}
    return {"handled": True, "ok": False, "reply": "ما لقيت هالهدف بين أهدافك النشطة. حاول بكلمة أخرى؟"}


GOAL_TOOLS = [
    {
        "name": "goal_set",
        "description": "سجّلي هدفاً جديداً للمستخدم وتابعيه",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "نص الهدف"},
                "deadline": {"type": "string", "description": "الموعد النهائي (اختياري، مثل: 2026-06-01)"},
            },
            "required": ["goal"],
        },
        "handler": goal_set,
    },
    {
        "name": "goal_list",
        "description": "اعرضي أهداف المستخدم النشطة أو المكتملة",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "active (افتراضي) | done"},
            },
            "required": [],
        },
        "handler": goal_list,
    },
    {
        "name": "goal_done",
        "description": "احتفلي وسجّلي اكتمال هدف",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "نص الهدف أو جزء منه"},
            },
            "required": ["goal"],
        },
        "handler": goal_done,
    },
]
