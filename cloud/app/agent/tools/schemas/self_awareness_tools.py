"""Self-awareness meta-tool: report Sandy's available capabilities + the
live health of each one (M6b).

Single source of truth: the ToolRegistry. Anything registered shows up
here; anything not registered doesn't — keeping the agent honest about
what it can / can't actually do right now."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from app.agent.tools.registry import get_registry

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


# Arabic category labels + short Arabic summary for each bucket. A tool falls in
# the first bucket with a marker that appears anywhere in its name (so
# "digital_gift" and "list_photos" match too). الترتيب يحدد ترتيب العرض.
_CATEGORIES = (
    ("📝 المهام",       ("task_",),                    "إضافة، تعديل، حذف، وإكمال المهام"),
    ("⏰ التذكيرات",     ("reminder_",),                 "تذكير بوقت محدد أو متكرر"),
    ("🎨 الصور",         ("image_", "photo"),            "توليد صور، تعديلها، وصفها، وألبوم صورك"),
    # كانت «الهاردوير» على بادئة `hardware_` وما في ولا أداة بتبدأ فيها، فالبند
    # ما كان بينعرض أبداً. والوصف بيقول «المربوطة بحسابك» لأنّ السجل عام مش
    # لكل مستأجر — يعني هالسطر بينقال حتى لمين ما عنده ولا جهاز.
    ("🛠️ الأجهزة",       ("device_", "scene_"),          "تشغيل وإطفاء الأجهزة المربوطة بحسابك وتطبيق مشاهد الغرفة، إذا عندك أجهزة"),
    ("🔍 البحث",         ("research_", "fetch_url", "share_interesting"), "بحث على الويب وتلخيص النتائج"),
    ("🎁 الهدايا",       ("gift",),                      "شعر، نكتة، لغز، أو كلمة حلوة"),
    ("🎯 الأهداف",       ("goal_",),                     "تتبع أهدافك وتقدمك عليها"),
    ("🔮 رسائل المستقبل", ("message_to_self",),           "كتابة رسالة لنفسك يتم تسليمها بوقت لاحق"),
    ("💡 العصف الذهني",  ("brainstorm_",),               "جلسات تخطيط وخطط محفوظة"),
    ("📚 الحياة اليومية", ("focus_", "book_", "reading_", "habit_", "journal_", "expense_", "shopping_"),
     "تركيز، كتب، عادات، يوميات، مصاريف، وقائمة تسوّق"),
    ("🧠 الذاكرة",       ("memory_",),                   "حفظ معلومات عنك واسترجاعها"),
    ("🔧 الدردشة",       ("chat_", "ask_", "request_", "pending_"), "حوار، أسئلة توضيحية، وتأكيدات"),
)


def _bucket_for(name: str) -> int:
    """يرجع index الـ bucket المناسب — أو -1 إذا ما في تصنيف."""
    for idx, (_label, prefixes, _desc) in enumerate(_CATEGORIES):
        if any(p in name for p in prefixes):
            return idx
    return -1


def get_capabilities_handler(
    args: Dict[str, Any], ctx: "DispatchContext"
) -> Dict[str, Any]:
    """Return a grouped, owner-friendly summary of every registered tool
    plus a callout for any that are currently degraded.

    Args:
        scope (str, optional): "all" (default) or "degraded".
    """
    scope = str((args or {}).get("scope") or "all").strip().lower()
    caps = get_registry().describe_capabilities()
    degraded = [c for c in caps if c.get("health", {}).get("status") == "degraded"]

    if scope == "degraded":
        if not degraded:
            return {
                "handled": True,
                "reply": "كل قدراتي شغالة تمام حالياً 👌",
            }
        lines = ["⚠️ القدرات المعطّلة حالياً:"]
        for c in degraded:
            h = c.get("health", {})
            label_idx = _bucket_for(c["name"])
            cat_label = _CATEGORIES[label_idx][0] if label_idx >= 0 else "أخرى"
            fail_pct = int((1 - h.get("success_rate", 1.0)) * 100)
            line = (
                f"• {cat_label} — {fail_pct}% فشل في آخر "
                f"{h.get('n_calls', 0)} محاولة"
            )
            if h.get("last_error"):
                line += f"\n   (آخر خطأ: {h['last_error'][:80]})"
            lines.append(line)
        return {"handled": True, "reply": "\n".join(lines)}

    # Default scope: عرض مجمّع بالعربي مع وصف قصير
    buckets: Dict[int, int] = {}
    other_count = 0
    for c in caps:
        idx = _bucket_for(c["name"])
        if idx == -1:
            other_count += 1
        else:
            buckets[idx] = buckets.get(idx, 0) + 1

    lines: List[str] = []
    lines.append(f"🧰 عندي {len(caps)} قدرة، موزّعة هيك:")
    lines.append("")
    for idx, (label, _prefixes, desc) in enumerate(_CATEGORIES):
        count = buckets.get(idx, 0)
        if count == 0:
            continue
        lines.append(f"{label} — {desc} ({count})")
    if other_count:
        lines.append(f"🧰 أخرى ({other_count})")

    if degraded:
        lines.append("")
        lines.append(
            f"⚠️ في {len(degraded)} قدرة معطّلة حالياً — اسأليني "
            f"'شو القدرات المعطّلة؟' للتفاصيل."
        )
    return {"handled": True, "reply": "\n".join(lines)}


SELF_AWARENESS_TOOLS = [
    {
        "name": "get_capabilities",
        "description": (
            "قدرات ساندي وحالتها: 'شو بتقدري تعملي؟'، 'وريني قدراتك'، "
            "'في أداة معطّلة؟'، 'بتشتغل كل ادواتك؟'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["all", "degraded"],
                    "description": "degraded = المعطّلة بس",
                },
            },
            "required": [],
        },
        "handler": get_capabilities_handler,
    },
]
