"""Core agent tools — persistent memory (MongoDB) + web fetch.

memory_store/recall تحفظ في MongoDB فتنجو من إعادة التشغيل؛ fetch_url
يجلب صفحة ويب عبر HTTP مباشر. كلها Python handlers (لا MCP/Node).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


# Memory adapters — stored in MongoDB so they survive restarts.

_COLL = "sandy_memories"


def _mem_db(ctx: "DispatchContext"):
    return ctx.mongo_db[_COLL] if ctx.mongo_db is not None else None


def memory_store(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    content = str(args.get("content", "")).strip()
    if not content:
        return {"handled": True, "reply": "شو اللي تريديني أحفظه؟"}

    coll = _mem_db(ctx)
    if coll is None:
        return {"handled": True, "reply": "دوّنتها 📝"}  # graceful in tests

    from datetime import datetime, timezone
    from app.utils.user_profiles import current_user_id

    uid = current_user_id()
    if not uid:
        # fail-closed: no tenant in context → never write to a shared bucket.
        return {"handled": True, "reply": "دوّنتها 📝"}
    coll.insert_one({
        "chat_id": uid,
        "label": str(args.get("label") or "user_fact").strip(),
        "content": content,
        "created_at": datetime.now(timezone.utc),
    })
    return {"handled": True, "reply": "دوّنتها 📝"}


def memory_recall(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"handled": True, "reply": "شو تبحثين عنه في ذاكرتي؟"}

    coll = _mem_db(ctx)
    if coll is None:
        return {"handled": True, "reply": "ما عندي ذكريات محفوظة بعد."}

    from app.utils.user_profiles import current_user_id

    uid = current_user_id()
    if not uid:
        # fail-closed: no tenant → never read a shared bucket.
        return {"handled": True, "reply": "ما عندي ذكريات محفوظة بعد."}

    # Try regex match on content first
    docs = list(coll.find(
        {"chat_id": uid, "content": {"$regex": query, "$options": "i"}},
        {"_id": 0, "content": 1},
        limit=10,
    ))

    # Broad query (e.g. "شو تعرفيه عني") → return all
    if not docs:
        docs = list(coll.find(
            {"chat_id": uid},
            {"_id": 0, "content": 1},
            sort=[("created_at", -1)],
            limit=20,
        ))

    lines = [c for d in docs if (c := str(d.get("content", "")).strip())]
    if not lines:
        return {"handled": True, "reply": "ما عندي ذكريات محفوظة بعد."}

    return {"handled": True, "reply": "\n".join(f"• {c}" for c in lines)}


# Fetch adapter — plain requests, no MCP needed.

def _html_to_text(html: str, max_length: int = 4000) -> str:
    """يشيل HTML tags ويرجع نص نظيف مقسم بفقرات."""
    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # كسر السطر عند عناصر الهيكل
    text = re.sub(r"<(?:br|/p|/div|/h[1-6]|/li|/tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(?:h[1-6])[^>]*>", "\n## ", text, flags=re.IGNORECASE)
    text = re.sub(r"<(?:li)[^>]*>", "\n• ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # دمج السطور الفارغة المتكررة
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = text.strip()
    if len(text) > max_length:
        text = text[:max_length] + "\n…"
    return text


_SUMMARIZE_THRESHOLD = 1500  # حروف — فوقها نلخص بالـ AI


def _ai_summarize(text: str, url: str, fn) -> str:
    """يلخص النص الطويل عبر LLM ويرجع ملخص عربي موجز."""
    try:
        messages = [
            {
                "role": "system",
                "content": "أنت مساعد. لخّص النص التالي بالعربية في فقرة واحدة أو فقرتين بلغة سهلة ومفهومة.",
            },
            {
                "role": "user",
                "content": f"الرابط: {url}\n\n{text[:8000]}",
            },
        ]
        result = fn(messages=messages, max_tokens=600, temperature=0.3)
        if isinstance(result, str):
            return result.strip()
        # Azure/OpenAI response object
        return result.choices[0].message.content.strip()
    except Exception:
        return text[:1500] + "\n…"


def fetch_url(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    import requests

    url = str(args.get("url", "")).strip()
    if not url:
        return {"handled": True, "reply": "أعطيني الرابط."}

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Sandy-Bot/1.0"})
        resp.raise_for_status()
        text = _html_to_text(resp.text, max_length=8000)
        if not text:
            return {"handled": True, "reply": "الصفحة فارغة أو ما فيها نص."}

        if len(text) > _SUMMARIZE_THRESHOLD and ctx.create_chat_completion_fn:
            summary = _ai_summarize(text, url, ctx.create_chat_completion_fn)
            return {"handled": True, "reply": summary}

        return {"handled": True, "reply": text[:4000] + ("\n…" if len(text) > 4000 else "")}
    except Exception as exc:
        return {"handled": True, "reply": f"ما قدرت أجلب الصفحة: {exc}"}


# Schemas

MCP_TOOLS = [
    {
        "name": "memory_store",
        "description": "احفظي معلومة أو ملاحظة في الذاكرة الدائمة",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "المعلومة أو الملاحظة المراد حفظها"},
                "label": {"type": "string", "description": "تسمية تصنيفية اختيارية مثل 'تفضيلات' أو 'عمل'"},
            },
            "required": ["content"],
        },
        "handler": memory_store,
    },
    {
        "name": "memory_recall",
        "description": "ابحثي في الذاكرة عن معلومات سبق حفظها",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "ما تبحث عنه في الذاكرة"},
            },
            "required": ["query"],
        },
        "handler": memory_recall,
    },
    {
        "name": "fetch_url",
        "description": "اجلبي محتوى صفحة ويب من رابط URL",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "رابط الصفحة"},
                "max_length": {"type": "integer", "description": "الحد الأقصى للأحرف (افتراضي 5000)"},
            },
            "required": ["url"],
        },
        "handler": fetch_url,
    },
]
