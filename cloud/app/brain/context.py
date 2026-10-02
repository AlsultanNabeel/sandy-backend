"""What the model knows at the start of a turn, built once per turn."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import PyMongoError

from app.brain.persona import build_effective_persona
from app.utils.ltm_crypto import decrypt_field
from app.blocks import _base, entries, habits
from app.blocks.kinds import LIST, LOG, get_kind
from app.utils.time import USER_TZ
from app.utils.time_awareness import time_awareness_block
from app.utils.user_profiles import address_instruction

logger = logging.getLogger(__name__)

MAX_FACTS = 30
STATE_ROWS = 15
TOP_ENTRIES = 8
# Log kinds the state block leaves out: facts have their own block, the rest are not edited by hand.
_NOT_SHOWN = ("fact", "summary", "habit", "mood")
# Atlas vector index on sandy_entries.embedding (filters: user_id, kind); see ARCHITECTURE_MAP.
VECTOR_INDEX = "entries_vector"
# Messages of the conversation the model sees (twelve exchanges).
RECENT_TURNS = 24
_NOISE = re.compile(r"^<noise>$|[\u3040-\u30ff\u4e00-\u9fff]")

_RULES = """
كيف تشتغلي:
- افهمي المقصود، مش الكلمات. الطلب الملفوف أو الناقص افهميه من السياق ومن «وضعه هلأ» تحت،
  ونفّذي على أقرب فهم معقول. اسألي بس إذا في احتمالين حقيقيين، وسؤال واحد قصير.
- لما يحكي عن إشي موجود («تذكير الأكل»، «المهمة تبعت الجيم»، «الأولى»)، لاقيه بـ«وضعه هلأ»
  وعدّليه بالـ id تبعه. ما تعملي عنصر جديد إذا في واحد بيشبهه، عدّلي الموجود.
- عندك أدوات حقيقية؛ ما تقولي إنك عملتي إشي إلا لما ترجعلك نتيجته.
- إشي صار (صرفت، قريت، رحت، أكلت) → remember بالنوع المناسب (صرفت خمسين على الغدا →
  kind=expense، data.amount=50، data.category=food؛ التصنيفات: food transport shopping
  bills fun health other). إشي لازم ينعمل → list_add (مهمة، تسوّق، هدف). إشي بوقت → schedule.
- الأوقات: ما تحسبي ساعات ولا فرق توقيت. نسبي («بعد نص ساعة»، «أجّليه شوي») → in_minutes
  أو shift_minutes، و«شوي» ربع ساعة. محدد («عالخمسة»، «بكرا الصبح») → حطي كلامه زي ما هو بـ when.
- مهمة بتتكرر («كل يوم»، «كل أسبوع») → list_add مع data.repeat=daily|weekly|monthly.
  عادة بأيام معيّنة → list=habits مع data.days (1 الأحد … 7 السبت) و data.time «HH:MM».
- حكى إنه هو اشترى أو جاب شي موجود بقائمة التسوق (بأي كلام): list_update بالـ id: done=true، أو
  qty بالباقي لو جاب جزء بس. لو ذكر سعر، كمان remember kind=expense. اللي مش بالقائمة ما
  تضيفيه. قصة عن غيره، أو شي بدّه يشتريه، مش شراء.
- «لا خلص احذفيه»، «غلط»، «ارجعي عنه»، «مش هيك» عن إشي عملتيه بردّك اللي قبل → undo_last،
  ولا تقولي «ماشي» بدون ما تنفّذي. لو بدّه يعدّله بس (مش يلغيه) → list_update / schedule_update بالـ id.
- معلومة ثابتة عنه → remember kind=fact. شعور قوي → remember kind=mood مرة وحدة بالدور.
- تصحيح لإشي بالسجلّ («لا قصدي أربعين مش خمسين») أو «احذفي هالمصروف» → log_update بالـ id من
  «سجّل اليوم». معلومة عنه تغيّرت («نقلت بيت جديد») → log_update للمعلومة القديمة بالنص الجديد، مش
  remember جديد. «انسي إني…» → log_update delete للمعلومة.
- «رجّعي الغرفة زي ما كانت» بعد مشهد → room_restore.
- سؤال عن محفوظ مش ظاهر تحت (مصاريف، سجل قديم، محادثات سابقة) → recall. «لخّصيلي» → summarize.
- ردّك قصير وطبيعي، بدون JSON وبدون أرقام تعريف.
"""


def _plain(e: Dict[str, Any]) -> str:
    """The row's text, decrypted; "" when it is still ciphertext (no key, wrong key)."""
    text = decrypt_field(e.get("text") or "")
    return "" if text.startswith("enc:") else text.strip()


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", text).strip().lower()


def profile_block(user_id: str) -> str:
    """What the user told her at first open and in the daily questions
    (`sandy_users.onboarding`), so she greets them by name on every channel."""
    from app.features import users_store

    if not user_id:
        return ""
    onboarding = (users_store.get_user(user_id) or {}).get("onboarding") or {}
    name = str(onboarding.get("preferred_name") or "").strip()
    raw = onboarding.get("interests")
    interests = [str(i).strip() for i in raw if str(i).strip()] if isinstance(raw, list) else []
    notes = str(onboarding.get("notes") or "").strip()
    raw = onboarding.get("nudge_answers")
    answers = [str(v).strip() for v in raw.values() if str(v).strip()] if isinstance(raw, dict) else []
    parts: List[str] = []
    if name:
        parts.append(f"نادِ المستخدم باسم «{name}»")
    if interests:
        parts.append("اهتماماته: " + "، ".join(interests[:8]))
    if notes:
        parts.append(f"عن نفسه: {notes[:300]}")
    if answers:
        # The newest six: nearer to how they are today, and the list only grows.
        parts.append("قال عن حاله: " + " · ".join(answers[-6:]))
    return "[ملف المستخدم: " + " · ".join(parts) + "]" if parts else ""


def facts_block(limit: int = MAX_FACTS) -> str:
    """What she knows about him: newest first, repeats and one-word scraps left out."""
    seen, lines = set(), []
    for e in entries.list_entries("fact", limit=limit * 3):
        text = _plain(e)
        key = _key(text)
        if len(key.split()) < 2 or key in seen:
            continue
        seen.add(key)
        lines.append(f"- {text} #{e['id']}")
        if len(lines) == limit:
            break
    return "معلومات بتعرفيها عنه (استعملي الـ id لما تتغيّر أو تنحذف):\n" + "\n".join(lines) if lines else ""


def _when(value: Any) -> str:
    """In his time zone, the same clock as «الآن» at the end of the prompt."""
    if not hasattr(value, "astimezone"):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(USER_TZ).strftime("%Y-%m-%d %H:%M")


def state_block(rows: int = STATE_ROWS) -> str:
    """What is on his plate right now, with ids, so a vague mention («تذكير الأكل»)
    is resolved by understanding and acted on by id, not by matching words."""
    from app.blocks import items, schedules

    parts: List[str] = []
    open_items = items.list_items(None, done=False, limit=rows * 3)
    by_list: Dict[str, List[str]] = {}
    for i in open_items:
        due = f" (موعدها {_when(i.get('due'))})" if i.get("due") else ""
        by_list.setdefault(i.get("list") or "", []).append(f"- {i.get('text', '')}{due} #{i['id']}")
    for name, lines in by_list.items():
        row = get_kind(LIST, name)
        label = f"{row.ar} ({name})" if row else name
        parts.append(f"قائمة {label}:\n" + "\n".join(lines[:rows]))
    # Reminders only: a message to his future self stays sealed until it is due.
    upcoming = schedules.list_schedules("reminder", status="pending", limit=rows)
    if upcoming:
        parts.append("التذكيرات الجاية:\n" + "\n".join(
            f"- {s.get('text', '')} ({_when(s.get('fire_at'))}"
            f"{', بتتكرر' if s.get('recurrence') else ''}) #{s['id']}" for s in upcoming))
    logged = _logged_today(rows)
    if logged:
        parts.append("سجّل اليوم:\n" + "\n".join(logged))
    if any(p.startswith("قائمة العادات") for p in parts):
        # The same numbers the app shows («كم يوم التزمت؟»), from one place.
        h = habits.progress()
        parts.append(f"التزامه بالعادات: {h['committed_days']} يوم التزم فيه بكل عادات اليوم، "
                     f"والسلسلة هلأ {h['streak']} يوم ورا بعض.")
    if not parts:
        return "وضعه هلأ: ما عنده مهام مفتوحة ولا تذكيرات جاية."
    return "وضعه هلأ (استعملي الـ id لما تعدّلي):\n" + "\n\n".join(parts)


def _logged_today(rows: int) -> List[str]:
    """Today's log lines with ids, so «لا قصدي أربعين» or «احذفي هالمصروف» lands on the row."""
    start = datetime.now(USER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    lines = []
    for e in entries.list_entries(since=start, exclude=_NOT_SHOWN, limit=rows):
        text = _plain(e)
        if not text:
            continue
        row = get_kind(LOG, e.get("kind") or "")
        amount = (e.get("data") or {}).get("amount")
        lines.append(f"- {row.ar if row else e.get('kind')}: {text}"
                     f"{f' ({amount:g})' if isinstance(amount, (int, float)) else ''} #{e['id']}")
    return lines


def _words(message: str) -> List[str]:
    return [w for w in re.findall(r"\w+", message or "") if len(w) >= 3][:8]


def similar_entries(message: str, k: int = TOP_ENTRIES,
                    kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Top-k log entries for this message (of ``kind``, else every kind but facts,
    summaries and habit ticks): the vector index first, word search when it has nothing."""
    coll = _base.coll(_base.ENTRIES)
    if coll is None or not (message or "").strip():
        return []
    # A greeting or a two-word order has nothing to look up (an asked-for kind always does).
    if kind is None and len(message.split()) < 3:
        return []
    vector = entries.embed_text(message)
    # Facts are already in the prompt; summaries are recall's job; habit ticks are not memories.
    base_q: Dict[str, Any] = {"kind": kind or {"$nin": ["fact", "summary", "habit"]}}
    if vector:
        try:
            docs = coll.vector_search(vector, index=VECTOR_INDEX, k=k, filter=base_q)
        except (PyMongoError, NotImplementedError) as exc:  # no index, or no Atlas (tests)
            logger.warning("[context] vector search unavailable: %s", exc)
            docs = []
        if docs:
            return [_base.out(d) for d in docs]
    words = _words(message)
    if not words:
        return []
    q = {**base_q, "$or": [_base.text_filter(w) for w in words]}
    return [_base.out(d) for d in coll.find(q, {"embedding": 0}).sort("at", -1).limit(k)]


def _entry_line(e: Dict[str, Any]) -> str:
    at = e.get("at")
    day = at.strftime("%Y-%m-%d") if hasattr(at, "strftime") else ""
    return f"- [{e.get('kind')} {day}] {_plain(e)}"


CHAT_CHANNEL = ("هلأ إنتِ بالشات المكتوب بالتطبيق: ردّك بينقرا مش بينسمع، فالإيموجي الدافية "
                "مسموحة. ما تحكي إنك بتسمعيه.")
SPOKEN_CHANNEL = ("هلأ إنتِ بتحكي معه بالصوت: ردّك بينسمع، فجمل قصيرة بدون إيموجي ولا رموز.")


_ARABIC = re.compile(r"[\u0600-\u06ff]")
_LATIN = re.compile(r"[A-Za-z]")


def reply_language(message: str) -> str:
    """The last line of the prompt: this message's language, whatever came before.
    English when it has more Latin letters than Arabic ones, else Arabic."""
    english = len(_LATIN.findall(message or "")) > len(_ARABIC.findall(message or ""))
    return ("This message is in English: write your whole reply in English only, "
            "with no Arabic word in it." if english else
            "هالرسالة بالعربي: ردّك كله بالعربي بلهجتك، بدون ولا كلمة إنجليزي.")


def build_system(user_id: str, message: str,
                 history: Optional[List[Dict[str, Any]]] = None, *, spoken: bool = False) -> str:
    """Steady parts first, changing parts last: the provider caches an unchanged
    prefix, so the persona and rules are read once, and the clock never breaks it.
    The channel line comes after the persona, so it wins over a persona written for voice."""
    parts = [build_effective_persona(user_id or None), address_instruction(), _RULES,
             SPOKEN_CHANNEL if spoken else CHAT_CHANNEL]
    try:
        parts.append(profile_block(user_id))
        parts.append(facts_block())
        parts.append(state_block())
        related = [e for e in similar_entries(message) if _plain(e)]
        if related:
            parts.append("من سجلّه (ممكن يفيد):\n" + "\n".join(_entry_line(e) for e in related))
    except Exception as exc:  # noqa: BLE001 — memory is never worth a failed reply
        logger.warning("[brain] memory context skipped: %s", exc)
    parts.append(time_awareness_block(history))
    parts.append(reply_language(message))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def history_messages(history: Optional[List[Dict[str, Any]]],
                     limit: int = RECENT_TURNS) -> List[Dict[str, str]]:
    out = []
    for m in (history or [])[-limit:]:
        role, content = m.get("role"), str(m.get("content") or "").strip()
        # Misheard audio («<noise>», a line of Japanese) only confuses the next reply.
        if role in ("user", "assistant") and content and not _NOISE.search(content):
            out.append({"role": role, "content": content})
    return out
