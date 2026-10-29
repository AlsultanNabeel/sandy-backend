"""Web research for the brain's `web_search`: Exa snippets, summarised in one model call."""

import logging
from typing import Dict, List
from urllib.parse import urlparse

from app.config import EXA_API_KEY
from app.integrations.exa_client import search_exa
from app.brain import lang

logger = logging.getLogger(__name__)

MAX_RESULTS = 8
SHOWN_RESULTS = 5
_SUMMARY_SYSTEM = (
    "أنت ساندي، مساعدة ذكية. لخّص نتائج البحث بلغة طلب المستخدم (عربي أو إنجليزي) "
    "بشكل مختصر وواضح ومرتب حسب طلب المستخدم. "
    "لا تبدأ بـ'تفضل' أو كلمات فارغة — ابدأ مباشرة بالمعلومات."
)


def _short_url(u: str) -> str:
    try:
        return urlparse(u).netloc.removeprefix("www.") or u
    except ValueError:
        return u


def _with_sources(body: str, sources: List[str]) -> str:
    body = str(body or "").strip() or lang.say("research_no_summary")
    lines = [f"{i}. {_short_url(url)}" for i, url in enumerate(sources[:5], 1)]
    if lines:
        return "\n\n".join((lang.say("research_summary", body=body),
                             lang.say("research_sources") + "\n" + "\n".join(lines)))
    return lang.say("research_summary", body=body)


def web_results(query: str) -> List[Dict[str, str]]:
    """The search's own results (title, url, text), no model: what a task's check compares.
    Raises when the search cannot run (no service, the provider failed)."""
    if not EXA_API_KEY:
        raise RuntimeError("no web search service configured")
    results = search_exa(query, exa_api_key=EXA_API_KEY, num_results=MAX_RESULTS) or []
    out = []
    for r in results[:MAX_RESULTS]:
        row = {"title": (r.get("title") or "").strip(), "url": (r.get("url") or "").strip(),
               "text": (r.get("text") or "")[:400].strip()}
        if row["title"] or row["text"]:
            out.append(row)
    return out


def web_answer(query: str, user_message: str) -> str:
    """The answer to a web question, in the turn's language, with its sources; a sentence saying so
    when the search could not run or found nothing."""
    if not EXA_API_KEY:
        return lang.say("research_no_service")
    try:
        results = web_results(query)
    except Exception as exc:  # noqa: BLE001 — provider boundary
        logger.warning("[research] Exa call raised: %s", exc)
        return lang.say("research_error", query=query)
    if not results:
        return lang.say("research_none", query=query)

    snippets: List[str] = []
    sources: List[str] = []
    for r in results:
        title, text, url = r["title"], r["text"], r["url"]
        line = f"- {title}" if title else ""
        if text:
            line += f": {text}" if line else f"- {text}"
        if line:
            snippets.append(line)
            if url:
                sources.append(url)
    if not snippets:
        return lang.say("research_unclear", query=query)

    from app.brain import background
    from app.utils.user_profiles import current_user_id

    reply = ""
    try:
        response = background.call("web_summary", [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": (f"طلب المستخدم: {user_message}\n\n"
                                         "نتائج البحث:\n" + "\n".join(snippets))}],
            priority=background.DIRECT, user_id=current_user_id(), temperature=0.3,
            max_tokens=600)
        reply = (response.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — provider boundary; the snippets still answer
        logger.warning("[research] summary failed: %s", exc)
    return _with_sources(reply or "\n".join(snippets[:SHOWN_RESULTS]), sources)
