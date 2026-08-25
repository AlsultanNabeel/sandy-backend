"""تذكّر أسماء العلاقات المهمة.

Sandy بتطلع أسماء الأهل والأصحاب والزملاء من رسائل المستخدم، بتخزّنهم
في sandy_memories، وبترجّعهم في soul_node عشان تغني persona_snippet.

نفس نمط الحفظ اللي في emotional_ltm.py و style_memory.py، بـ label="relationship".
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.db import get_db
from app.utils.tenant_db import scoped
from app.utils.user_profiles import current_user_id

logger = logging.getLogger(__name__)


_COLL = "sandy_memories"
_LABEL = "relationship"


def _coll():
    """The tenant-scoped handle, and the only way into storage here.

    This module used to take `chat_id` and `mongo_db` and write on the raw
    collection with the tenant stamped by hand — the pattern `tenant_db` exists
    to abolish, and the one `ARCHITECTURE_MAP` §2.6 says must never come back on
    a request path. It was invisible to `test_tenant_scoping_guard.py`, so a
    forgotten filter would have been a cross-tenant leak with nothing watching.

    It could not move before: these writers run on background threads and the
    tenant lives in a `ContextVar` that did not cross one. `submit_background`
    carries it now (§2.5), so the scoping works where it is actually called.
    """
    return scoped(get_db(), _COLL, field="chat_id")



# كلمة العلاقة زي ما يكتبها المستخدم، والكلمة الموحّدة اللي بنخزّنها
_RELATION_TERMS = {
    "أبوي": "والد", "ابوي": "والد", "بابا": "والد", "والدي": "والد",
    "أمي": "والدة", "امي": "والدة", "ماما": "والدة", "والدتي": "والدة",
    "أخوي": "أخ", "اخوي": "أخ", "أخويا": "أخ", "اخويا": "أخ",
    "أختي": "أخت", "اختي": "أخت", "أختا": "أخت",
    "زوجتي": "زوجة", "مرتي": "زوجة", "حرمتي": "زوجة",
    "زوجي": "زوج", "جوزي": "زوج",
    "ابني": "ابن", "ولدي": "ابن",
    "بنتي": "بنت", "ابنتي": "بنت",
    "صديقي": "صديق", "صاحبي": "صديق", "رفيقي": "صديق",
    "صديقتي": "صديقة", "صاحبتي": "صديقة",
    "جاري": "جار", "جارتي": "جارة",
    "مديري": "مدير", "زميلي": "زميل", "زميلتي": "زميلة",
    "حبيبي": "شريك", "حبيبتي": "شريكة",
    "خالي": "خال", "خالتي": "خالة", "عمي": "عم", "عمتي": "عمة",
}

# بنقبل بس الحالات الواضحة عشان نقلّل الـ false positives، يعني لازم
# يكون في marker صريح زي "اسمه" أو "اسمها"، مثل "صديقي اسمه أحمد".
# أي شي بدون marker بنتجاهله.
_RELATION_NAME_RE = re.compile(
    r"(?:^|[\s،,])[وبلف]?(?P<rel>" + "|".join(_RELATION_TERMS.keys()) + r")\s+"
    r"(?:اسمه|اسمها|يسمى|تسمى)\s+(?P<name>[ء-ي]{2,15})\b"
)


def detect_relationships(message: str) -> List[Tuple[str, str]]:
    """يطلّع (relation, name) من الرسالة، أو قائمة فاضية لو ما في.

    >>> detect_relationships("أخوي اسمه محمد")
    [('أخ', 'محمد')]
    """
    found: List[Tuple[str, str]] = []
    if not message:
        return found

    for m in _RELATION_NAME_RE.finditer(message):
        rel_word = m.group("rel")
        name = m.group("name").strip()
        relation = _RELATION_TERMS.get(rel_word, rel_word)
        if name in _RELATION_TERMS or len(name) < 2:
            continue
        found.append((relation, name))
    return found


def save_relationship(
    relation: str,
    name: str,
) -> bool:
    """يحفظ علاقة جديدة. ما يكرّر نفس (relation, name) لو موجودة."""
    coll = _coll()
    if coll is None or not relation or not name:
        return False
    try:
        existing = coll.find_one(
            {"label": _LABEL, "relation": relation, "name": name},
            {"_id": 1},
        )
        if existing:
            return False
        coll.insert_one({
            "user_id": str(current_user_id() or ""),
            "label": _LABEL,
            "relation": relation,
            "name": name,
            "created_at": datetime.now(timezone.utc),
        })
        logger.info(f"[relationships] saved: {relation}={name}")
        return True
    except Exception as exc:
        logger.debug(f"[relationships] save failed: {exc}")
        return False


def get_relationships_context(
    limit: int = 10,
) -> Optional[str]:
    """يرجّع علاقات المستخدم كـ context لـ soul_node."""
    coll = _coll()
    if coll is None:
        return None
    try:
        docs = list(coll.find(
            {"label": _LABEL},
            {"_id": 0, "relation": 1, "name": 1},
            sort=[("created_at", -1)],
            limit=limit,
        ))
    except Exception:
        return None

    if not docs:
        return None

    parts = [f"{d['relation']} {d['name']}" for d in docs if d.get("name")]
    return "[علاقات: " + " · ".join(parts) + "]" if parts else None


def save_detected_relationships(
    message: str,
) -> int:
    """يكتشف ويحفظ بخطوة وحدة. بيستدعيه graph.py في thread بالخلفية."""
    saved = 0
    for relation, name in detect_relationships(message):
        if save_relationship(relation, name):
            saved += 1
    return saved
