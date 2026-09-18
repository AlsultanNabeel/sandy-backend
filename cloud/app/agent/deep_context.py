"""Recent search/options buffer, so a follow-up like "which is closest?" can be
answered from the results Sandy just showed instead of searching again."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List

from app.utils.time import USER_TZ

LAST_SEARCH_RESULTS_KEY = "last_search_results"

_COMPARISON_HINT = re.compile(
    r"(?:أحسن|احسن|أفضل|افضل|ارخص|أرخص|أغلا|اغلا|أقرب|اقرب|أبعد|ابعد|أسرع|اسرع|"
    r"اي\s+وحد|اي\s+واحد|أي\s+وحد|أي\s+واحد|أي\s+من(?:هم|هن)|اي\s+من|ومين|وش\s+المفضل|شو\s+المفضل|"
    r"(?:مش|مو)\s+عرف\s+اختار)",
    re.IGNORECASE,
)


def persist_last_search_results(
    session: Dict[str, Any],
    *,
    domain: str,
    query: str,
    items: List[Dict[str, Any]],
) -> None:
    """Store last surfaced options for comparative / grounding follow-ups."""
    sess = session if isinstance(session, dict) else {}
    clean_items: List[Dict[str, Any]] = []
    for it in items[:20]:
        if not isinstance(it, dict):
            continue
        row = it.get("row")
        title = str(it.get("title", "") or "").strip()[:500]
        url = str(it.get("url", "") or "").strip()[:500]
        snippet = str(it.get("snippet", "") or "").strip()[:900]
        if not title and url:
            title = url
        if title or snippet or url:
            clean_items.append(
                {
                    "row": row if isinstance(row, int) else len(clean_items) + 1,
                    "title": title or "بدون عنوان",
                    "url": url,
                    "snippet": snippet,
                }
            )
    sess[LAST_SEARCH_RESULTS_KEY] = {
        "domain": str(domain or "unknown").strip()[:80],
        "query": str(query or "").strip()[:300],
        "items": clean_items,
        "ts": datetime.now(USER_TZ).isoformat(),
    }


def places_to_search_items(
    places: List[Dict[str, Any]], limit: int = 12
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, p in enumerate((places or [])[:limit]):
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "") or "").strip()
        if not name:
            continue
        rating = p.get("rating") or ""
        addr = str(p.get("address", "") or "").strip()
        price = str(p.get("price_level", "") or "").strip()
        snip_parts = [x for x in (f"⭐{rating}", price, addr) if x]
        out.append(
            {
                "row": i + 1,
                "title": name,
                "url": str(p.get("maps_url", "") or "").strip(),
                "snippet": " — ".join(snip_parts)[:500],
            }
        )
    return out


def wants_comparison_grounded_in_search(normalized_message: str) -> bool:
    """Heuristic signal for Planner prompt (comparison without explicit noun)."""
    return bool(_COMPARISON_HINT.search(str(normalized_message or "")))
