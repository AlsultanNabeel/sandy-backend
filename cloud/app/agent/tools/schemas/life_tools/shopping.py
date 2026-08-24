"""shopping tools."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def shopping_add(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.shopping_store import add_items

    items = args.get("items")
    if not items:
        single = str(args.get("item", "")).strip()
        items = [single] if single else []
    if not items:
        return {"handled": True, "reply": "شو بدك أضيف عالقائمة؟"}
    n = add_items([str(x) for x in items])
    if n == 0:
        return {"handled": True, "reply": "كلهم موجودين عالقائمة أصلاً 🛒"}
    return {"handled": True, "reply": f"🛒 ضفت {n} عالقائمة." if n > 1 else f"🛒 ضفت «{items[0]}»."}


def shopping_list(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.shopping_store import list_items

    items = list_items()
    if not items:
        return {"handled": True, "reply": "قائمة التسوق فاضية 🛒"}
    lines = [f"{i}. {x['text']}" for i, x in enumerate(items, 1)]
    return {"handled": True, "reply": "🛒 قائمة التسوق:\n" + "\n".join(lines)}


def shopping_check(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.shopping_store import check_item

    name = check_item(str(args.get("item", "")))
    if not name:
        return {"handled": True, "ok": False, "reply": "ما لقيت هالعنصر بالقائمة."}
    return {"handled": True, "reply": f"✅ شطبت «{name}» — مبروك الشراء!"}


def shopping_remove(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.shopping_store import remove_item

    name = remove_item(str(args.get("item", "")))
    if not name:
        return {"handled": True, "ok": False, "reply": "ما لقيت هالعنصر بالقائمة."}
    return {"handled": True, "reply": f"🗑 حذفت «{name}» من القائمة."}


# ── العادات ──────────────────────────────────────────────────────────────────
