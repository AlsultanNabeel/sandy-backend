"""Web research for the brain's `web_search`: Exa snippets, summarised in one model call."""

import logging
from typing import Any, Callable, List, Optional
from urllib.parse import urlparse

from app.config import EXA_API_KEY
from app.integrations.exa_client import search_exa

logger = logging.getLogger(__name__)

MAX_RESULTS = 8
SHOWN_RESULTS = 5
_SUMMARY_SYSTEM = (
    "أنت ساندي، مساعدة ذكية. لخّص نتائج البحث باللغة العربية "
    "بشكل مختصر وواضح ومرتب حسب طلب المستخدم. "
    "لا تبدأ بـ'تفضل' أو كلمات فارغة — ابدأ مباشرة بالمعلومات."
)


def _short_url(u: str) -> str:
    try:
        return urlparse(u).netloc.removeprefix("www.") or u
    except ValueError:
        return u


def _with_sources(body: str, sources: List[str]) -> str:
    body = str(body or "").strip() or "ما قدرت ألخص النتائج بشكل واضح حالياً."
    lines = [f"{i}. {_short_url(url)}" for i, url in enumerate(sources[:5], 1)]
    if lines:
        return f"📌 الملخص:\n{body}\n\n📎 المصادر:\n" + "\n".join(lines)
    return f"📌 الملخص:\n{body}"


def web_answer(query: str, user_message: str,
               complete: Optional[Callable[..., Any]] = None) -> str:
    """The Arabic answer to a web question, with its sources; a sentence saying so
    when the search could not run or found nothing."""
    if not EXA_API_KEY:
        return "ما قدرت أكمل البحث — خدمة البحث غير متوفرة حالياً."
    try:
        results = search_exa(query, exa_api_key=EXA_API_KEY, num_results=MAX_RESULTS)
    except Exception as exc:  # noqa: BLE001 — provider boundary
        logger.warning("[research] Exa call raised: %s", exc)
        return f"ما قدرت أجد نتائج عن '{query}' — خطأ في الاتصال بخدمة البحث."
    if not results:
        return f"ما قدرت أجد نتائج عن '{query}' الآن. جرب مرة ثانية لاحقاً."

    snippets: List[str] = []
    sources: List[str] = []
    for r in results[:MAX_RESULTS]:
        title = (r.get("title") or "").strip()
        text = (r.get("text") or "")[:400].strip()
        url = (r.get("url") or "").strip()
        line = f"- {title}" if title else ""
        if text:
            line += f": {text}" if line else f"- {text}"
        if line:
            snippets.append(line)
            if url:
                sources.append(url)
    if not snippets:
        return f"ما قدرت أجد نتائج واضحة عن '{query}'."

    reply = ""
    if complete is not None:
        try:
            response = complete(temperature=0.3, max_tokens=600, messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": (f"طلب المستخدم: {user_message}\n\n"
                                             "نتائج البحث:\n" + "\n".join(snippets))}])
            reply = (response.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 — provider boundary; the snippets still answer
            logger.warning("[research] summary failed: %s", exc)
    return _with_sources(reply or "\n".join(snippets[:SHOWN_RESULTS]), sources)
