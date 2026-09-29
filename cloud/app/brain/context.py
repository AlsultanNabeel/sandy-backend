"""What the model knows at the start of a turn, built once per turn."""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional

from app.agent.context_builder import build_effective_persona
from app.agent.ltm_crypto import decrypt_field
from app.blocks import _base, entries
from app.utils.time_awareness import time_awareness_block
from app.utils.user_profiles import address_instruction

logger = logging.getLogger(__name__)

MAX_FACTS = 40
TOP_ENTRIES = 8
# How many recent vectors are scored in Python; the blocks have no Atlas index yet.
SCAN_ENTRIES = 400
RECENT_TURNS = 8

_RULES = """
طريقة شغلك بهالمحادثة:
- عندك أدوات حقيقية. أي طلب فيه حفظ أو تعديل أو حذف أو تذكير أو جهاز → استدعي الأداة المناسبة، وما تقولي إنك عملتي إشي إلا لما ترجعلك نتيجته.
- فرّقي بين تلات أشياء:
  • إشي صار (صرفت، قريت، رحت الجيم، نمت، أكلت) → remember بالنوع المناسب.
    مثال: «صرفت خمسين على الغدا» → remember kind=expense, text="غدا", data.amount=50.
  • إشي لازم ينعمل (مهمة، غرض تشتريه، هدف) → list_add.
    مثال: «لازم أشتري حليب» → list_add list=shopping, text="حليب".
  • إشي بوقت محدد → schedule. مثال: «ذكّريني بعد ساعة أشرب مي» → schedule.
- «شو عندي / شو مهامي / قديش صرفت» → recall. حطي اسم القائمة أو النوع بـ list أو kind
  (مهامي → list=tasks، مصاريفي → kind=expense)، والـ query بس لكلمة بتدوّري عليها.
- «لخّصيلي» → summarize ثم لخّصي الصفوف اللي رجعت.
- معلومة ثابتة عن المستخدم (اسمه، شغله، إشي بحبه) → remember بنوع fact.
- لو المستخدم حكى عن شعور قوي (متوتر، محبط، زعلان، معصّب، مبسوط، متحمّس) → remember بنوع mood و data.mood = stressed|frustrated|sad|angry|happy|excited، مرة وحدة بالدور.
- لو أداة رجعت needs_confirmation، اسألي المستخدم سؤال التأكيد بجملة وحدة.
- ردّك الأخير نص طبيعي قصير، بدون JSON وبدون أرقام تعريف.
"""


def _fact_line(e: Dict[str, Any]) -> str:
    text = e.get("text") or ""
    if (e.get("data") or {}).get("encrypted"):
        text = decrypt_field(text)
    return f"- {text}"


def facts_block(limit: int = MAX_FACTS) -> str:
    rows = entries.list_entries("fact", limit=limit)
    if not rows:
        return ""
    return "معلومات بتعرفيها عن المستخدم:\n" + "\n".join(_fact_line(e) for e in rows)


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _words(message: str) -> List[str]:
    return [w for w in re.findall(r"\w+", message or "") if len(w) >= 3][:8]


def similar_entries(message: str, k: int = TOP_ENTRIES) -> List[Dict[str, Any]]:
    """Top-k non-fact log entries for this message; text search without embeddings."""
    coll = _base.coll(_base.ENTRIES)
    if coll is None or not (message or "").strip():
        return []
    vector = entries.embed_text(message)
    base_q: Dict[str, Any] = {"kind": {"$ne": "fact"}}
    if vector:
        docs = list(coll.find({**base_q, "embedding": {"$ne": None}})
                    .sort("at", -1).limit(SCAN_ENTRIES))
        docs.sort(key=lambda d: _cosine(vector, d.get("embedding") or []), reverse=True)
        return [_base.out(d) for d in docs[:k]]
    words = _words(message)
    if not words:
        return []
    q = {**base_q, "$or": [_base.text_filter(w) for w in words]}
    return [_base.out(d) for d in coll.find(q, {"embedding": 0}).sort("at", -1).limit(k)]


def _entry_line(e: Dict[str, Any]) -> str:
    at = e.get("at")
    day = at.strftime("%Y-%m-%d") if hasattr(at, "strftime") else ""
    text = e.get("text") or ""
    if (e.get("data") or {}).get("encrypted"):
        text = decrypt_field(text)
    return f"- [{e.get('kind')} {day}] {text}"


def build_system(user_id: str, message: str,
                 history: Optional[List[Dict[str, Any]]] = None) -> str:
    parts = [build_effective_persona(user_id or None), address_instruction(), _RULES,
             time_awareness_block(history)]
    try:
        facts = facts_block()
        if facts:
            parts.append(facts)
        related = similar_entries(message)
        if related:
            parts.append("من سجلّ المستخدم (ممكن يفيد):\n"
                         + "\n".join(_entry_line(e) for e in related))
    except Exception as exc:  # noqa: BLE001 — memory is never worth a failed reply
        logger.warning("[brain] memory context skipped: %s", exc)
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def history_messages(history: Optional[List[Dict[str, Any]]],
                     limit: int = RECENT_TURNS) -> List[Dict[str, str]]:
    out = []
    for m in (history or [])[-limit:]:
        role, content = m.get("role"), m.get("content")
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": str(content)})
    return out
