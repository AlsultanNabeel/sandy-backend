"""Briefing helpers for Sandy facade."""

from __future__ import annotations
import logging

import re
from datetime import datetime
from typing import Any, Dict, List

from app.utils.time import USER_TZ


_SHOPPING_PREFIXES = re.compile(
    r"^(اشتري|اشتر|شراء|شري|جيب|جيبي|ابعت|ابعث)\s+(ال)?", re.UNICODE
)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s​]+", " ", text)
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
    text = _SHOPPING_PREFIXES.sub("", text).strip()
    return text


def _dedup(items: List[Dict]) -> List[Dict]:
    seen: set[str] = set()
    result = []
    for t in items:
        key = _normalize(t.get("text") or "")
        if key and key not in seen:
            seen.add(key)
            result.append(t)
    return result


def build_morning_briefing(*, memory: Dict[str, Any], mongo_db, tasks_file) -> str:
    from app.features.tasks_store import load_tasks
    from app.features.reminders_store import load_reminders
    from app.features.weather import get_weather, format_weather_for_prompt

    now = datetime.now(USER_TZ)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)

    tasks = load_tasks(mongo_db=mongo_db, tasks_file=tasks_file)
    # Today's reminders take the slot calendar events used to fill.
    todays_reminders = []
    try:
        for r in load_reminders(max_results=50):
            try:
                dt = datetime.fromisoformat(r.get("remind_at", ""))
                if dt <= today_end:
                    todays_reminders.append(r)
            except Exception:
                continue
    except Exception:
        todays_reminders = []

    city = str(memory.get("sandy_state", {}).get("home_city", "") or "").strip() or "October City"
    weather_raw = format_weather_for_prompt(get_weather(city))
    mood = str(memory.get("sandy_state", {}).get("mood", "neutral")).strip()

    # Raw data block the model writes the briefing from.
    active_tasks = _dedup([t for t in tasks if not t.get("done")])
    tasks_lines = []
    for t in active_tasks:
        text = (t.get("text") or "").strip()
        # `due` is a date-only midnight-UTC stamp; showing it as a time gave a
        # "03:00 AM" nobody set. Only `due_at` carries a real time.
        has_time = bool(str(t.get("due_at") or "").strip())
        raw_due = str(t.get("due_at") or t.get("due") or "").strip()
        due_label = ""
        if raw_due:
            try:
                if has_time:
                    dt = datetime.fromisoformat(raw_due.replace("Z", "+00:00")).astimezone(USER_TZ)
                    due_label = f" (موعد: {dt.strftime('%a %d/%m %I:%M %p')})"
                else:
                    d = datetime.fromisoformat(raw_due.replace("Z", "+00:00")).date()
                    due_label = f" (موعد: {d.strftime('%a %d/%m')})"
            except ValueError:
                logging.getLogger(__name__).debug("bad due %r", raw_due)
        tasks_lines.append(f"- {text}{due_label}")

    cal_lines = []
    for r in todays_reminders:
        text = (r.get("text", "") or "").strip()
        label = ""
        try:
            dt = datetime.fromisoformat(r.get("remind_at", "")).astimezone(USER_TZ)
            label = dt.strftime("%I:%M %p")
        except Exception:
            logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
        prefix = "🔁 " if r.get("is_recurring") else ""
        cal_lines.append(
            f"- {prefix}{text or 'تذكير'} @ {label}" if label else f"- {prefix}{text or 'تذكير'}"
        )

    data_block = f"""الطقس: {weather_raw}
المزاج المرصود: {mood}
المهام النشطة ({len(active_tasks)}):
{chr(10).join(tasks_lines) if tasks_lines else "لا توجد مهام"}
تذكيرات اليوم:
{chr(10).join(cal_lines) if cal_lines else "لا توجد تذكيرات"}"""

    from app.agent.context_builder import build_effective_persona
    from app.utils.user_profiles import (
        HAS_NO_NAME, address_instruction, current_user_id, speaker_label,
    )

    # الملخّص بيتبنى لصاحب الحساب اللي طلبه، مش لشخص مكتوب اسمه بالكود. المسار
    # بيمرّ من `execute_node` وهو جوّا سياق المستأجر، فالمعرّف موجود هون —
    # وتمريره لـ`build_effective_persona` كمان بيرجّع تعليماته ولهجته، وكانت
    # بتنزل للافتراضي لكل مستأجر.
    _uid = current_user_id()
    _name = speaker_label(_uid)
    # لام الجر مع «ال» التعريف بتدغم: ل + المستخدم = للمستخدم. بس ما منقدر
    # نحزر إذا «ال» بأول اسم هي أداة تعريف ولا جزء منه — «الياس» بتصير
    # «للياس»، وهاد اسم تاني. فالإدغام للكلمة اللي منملكها وحدها.
    _for = "للمستخدم" if _name == HAS_NO_NAME else f"لـ{_name}"
    prompt = f"""{build_effective_persona(_uid)}

اكتبي ملخص صباحي مختصر وطبيعي {_for} بناءً على البيانات أدناه فقط.
{address_instruction()}

قواعد صارمة:
- ابدئي بـ"صباح الخير ☀️" بشكل عفوي شامي
- اذكري الطقس بجملة واحدة خفيفة
- اجمعي المشتريات الموجودة في البيانات بجملة واحدة — لا تخترعي مشتريات من عندك
- اذكري المهام الأخرى بإيجاز
- اذكري تذكيرات اليوم لو في
- اختمي قبل الجملة الشخصية باقتراح ذكي لترتيب اليوم بسطر أو سطرين (شو يبدأ فيه وليش)
- اختمي بجملة واحدة شخصية شامية مختلفة كل يوم، بنفس صيغة المخاطبة أعلاه
- لا تكتبي قوائم منقطة ولا عناوين رسمية
- الطول الكلي: ٥-٨ أسطر فقط

البيانات (هاي هي فقط — لا تضيفي شي من عندك):
{data_block}"""

    try:
        from app.integrations.azure_intent_client import AzureIntentClient
        client = AzureIntentClient()
        result = client._generate_with_gemini(
            prompt,
            response_mime_type="text/plain",
            max_output_tokens=300,
            temperature=0.85,
        )
        if result:
            return result
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)

    # Fallback when the model call fails: plain structured text.
    tasks_block = "\n".join(tasks_lines[:6]) if tasks_lines else "ما في مهام"
    cal_block = "\n".join(cal_lines) if cal_lines else "ما في تذكيرات"
    return (
        f"صباح الخير ☀️\n\n"
        f"🌤 {weather_raw}\n\n"
        f"📋 مهامك:\n{tasks_block}\n\n"
        f"⏰ تذكيرات اليوم:\n{cal_block}"
    )
