"""Arabic and English are equal: the language of a turn, and every sentence the server
says itself in both.

A message is English when it has more Latin letters than Arabic ones, else Arabic; one
with no letters at all («2», «👍»), or only a word everyone uses in both («ok»), keeps the
language the conversation was in. The turn's
language is a context variable (`using`), set by `loop.run_turn` and read by `say`, so a
tool, the confirmation and the honesty check answer in it without being passed it.

Every phrase has both languages and the same slots (`tests/test_brain_language.py`). What
the model reads (notes, instructions) stays in one language; what the user reads is here.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

AR, EN = "ar", "en"

_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")
_current: ContextVar[str] = ContextVar("sandy_lang", default=AR)
# Said the same in Arabic and English chats: they name no language.
_BOTH_LANGUAGES = {"ok", "okay", "k", "kk"}


def of(text: str, fallback: Optional[str] = None) -> str:
    """The language a text is written in; ``fallback`` (else Arabic) when it has no letters."""
    latin, arabic = len(_LATIN.findall(text or "")), len(_ARABIC.findall(text or ""))
    if (not latin and not arabic) or re.sub(r"[^a-z]", "", (text or "").lower()) in _BOTH_LANGUAGES \
            and not arabic:
        return fallback or AR
    return EN if latin > arabic else AR


@contextmanager
def using(language: str) -> Iterator[str]:
    token = _current.set(EN if language == EN else AR)
    try:
        yield _current.get()
    finally:
        _current.reset(token)


def settle(language: str) -> None:
    """Inside `using`: the turn's language once more is known (the conversation's, for a
    message with no letters). `using` still puts back what was there before it."""
    _current.set(EN if language == EN else AR)


def current() -> str:
    return _current.get()


def for_user(user_id: str) -> str:
    """The user's own language: the app's setting, which starts as the phone's (`note`)."""
    if not user_id:
        return AR
    from app.features import users_store
    saved = (users_store.get_user(user_id) or {}).get("language")
    return EN if saved == EN else AR


def note(user_id: str, language: str) -> None:
    """Keep the language the phone sent when it changed; one the app does not speak is not."""
    language = str(language or "").strip().lower()[:2]
    if not user_id or language not in (AR, EN):
        return
    from app.features import users_store
    if (users_store.get_user(user_id) or {}).get("language") != language:
        users_store.set_language(user_id, language)


def say(key: str, **slots: object) -> str:
    """The phrase in the turn's language, its slots filled."""
    return PHRASES[key][_current.get()].format(**slots)


PHRASES = {
    "error": {"ar": "حصل خطأ، حاول مرة ثانية.",
              "en": "Something went wrong, please try again."},
    "gave_up": {"ar": "ما قدرت أكمّل هالطلب، جرّب تحكيه بطريقة تانية.",
                "en": "I couldn't finish that. Try saying it another way."},
    # A turn that broke after it wrote: it happened, so it is answered (and kept in the
    # send ledger as done), never run again by a resend.
    "after_writes": {"ar": "صار خطأ بنص الطلب بعد ما نفّذت جزء منه. شوف القوائم قبل ما تعيده.",
                     "en": "Something went wrong partway, after part of it was done. "
                           "Check your lists before asking again."},
    "done": {"ar": "تم ✅", "en": "Done ✅"},
    "cancelled": {"ar": "تمام، ما عملت إشي.", "en": "OK, I didn't do anything."},
    "confirm_question": {"ar": "متأكد إنك بدك {summary}؟ (اه/لأ)",
                         "en": "Are you sure you want to {summary}? (yes/no)"},
    "dropped": {"ar": "اعتبرتك ما بدك {summary}، فما عملت إشي.",
                "en": "I took it you don't want to {summary}, so I didn't do it."},
    "choice_question": {"ar": "لقيت أكتر من وحدة:\n{rows}\nأي وحدة؟ (رقمها، أو «كلهم»)",
                        "en": "I found more than one:\n{rows}\nWhich one? (its number, or «all»)"},
    # Lists and the log (`tools_blocks`).
    "sep": {"ar": "، ", "en": ", "},
    "names_last": {"ar": "{names} و{last}", "en": "{names} and {last}"},
    "names_more": {"ar": "{names} وكمان {n}", "en": "{names} and {n} more"},
    "something": {"ar": "إشي", "en": "entry"},
    "logged": {"ar": "سجّلتها ✅ «{text}»", "en": "Logged ✅ «{text}»"},
    "added": {"ar": "ضفت «{text}» ✅", "en": "Added «{text}» ✅"},
    "already_listed": {"ar": "«{text}» موجودة أصلاً بالقائمة", "en": "«{text}» is already on the list"},
    "qty_now": {"ar": "صاروا {qty}", "en": "now {qty}"},
    "existed_updated": {"ar": "«{text}» كانت موجودة، عدّلتها: {parts} ✅",
                        "en": "«{text}» was already there, so I updated it: {parts} ✅"},
    "edited": {"ar": "عدّلت {names} ✅", "en": "Updated {names} ✅"},
    "edited_to": {"ar": "عدّلت {names} لـ{time} ✅", "en": "Moved {names} to {time} ✅"},
    "finished": {"ar": "خلّصت {names} ✅", "en": "Marked {names} done ✅"},
    "deleted": {"ar": "حذفت {names} ✅", "en": "Deleted {names} ✅"},
    "cancelled_rows": {"ar": "لغيت {names} ✅", "en": "Cancelled {names} ✅"},
    "missing": {"ar": " (وفي {n} ما لقيتهم)", "en": " ({n} I couldn't find)"},
    "nothing_changed": {"ar": "ما تغيّر شي: ما في حقل جديد يتغيّر، والعنصر زي ما هو.",
                        "en": "Nothing changed: there's nothing new to change, it's as it was."},
    "nothing_logged": {"ar": "ما لقيت ولا {kind} مسجّل.", "en": "I couldn't find any {kind} logged."},
    "nothing_there": {"ar": "ما في إشي هون أصلاً.", "en": "There's nothing here."},
    "not_found": {"ar": "ما لقيت هالإشي، شكله انحذف أو تغيّر",
                  "en": "I couldn't find that, it may have been deleted or changed"},
    "not_found_named": {"ar": "ما لقيت «{said}»", "en": "I couldn't find «{said}»"},
    "not_found_closest": {"ar": "{reply}؛ أقرب إشي «{closest}». قصدك هو؟",
                          "en": "{reply}; the closest is «{closest}». Did you mean that?"},
    "held_gone": {"ar": "ما لقيت اللي سألتك عنه، شكله انحذف أو تغيّر.",
                  "en": "I couldn't find what I asked you about; it may have been deleted or changed."},
    # A held change's summary: its first word is the verb `confirm` reads a yes by.
    "held_delete": {"ar": "تحذف {names}", "en": "delete {names}"},
    "held_cancel": {"ar": "تلغي {names}", "en": "cancel {names}"},
    "held_change": {"ar": "تعدّل {names}", "en": "change {names}"},
    "held_finish": {"ar": "تخلّص {names}", "en": "finish {names}"},
    "which_list": {"ar": "أي قائمة بدك أفضّي؟", "en": "Which list should I empty?"},
    "what_to_delete": {"ar": "شو بدك أحذف بالزبط؟", "en": "What exactly should I delete?"},
    "checked_already": {"ar": "«{text}» مسجّلة اليوم أصلاً ✅", "en": "«{text}» is already checked off today ✅"},
    "checked_today": {"ar": "سجّلت «{text}» لليوم ✅", "en": "Checked off «{text}» for today ✅"},
    "scheduled": {"ar": "تمام، بذكّرك «{text}» {time} ⏰", "en": "OK, I'll remind you «{text}» at {time} ⏰"},
    "scheduled_alarm": {"ar": "تمام، حطّيت منبه «{text}» {time} ⏰", "en": "OK, alarm «{text}» set for {time} ⏰"},
    "scheduled_scene": {"ar": "تمام، بعمل «{text}» {time} ⏰", "en": "OK, I'll do «{text}» at {time} ⏰"},
    "undo_nothing": {"ar": "ما في إشي غيّرته بآخر أسبوع لأرجّعه.",
                     "en": "There's nothing I changed in the last week to put back."},
    "undo_not_found": {"ar": "ما لقيت «{said}» بين اللي غيّرته.",
                       "en": "I couldn't find «{said}» among what I changed."},
    "undo_failed": {"ar": "ما قدرت أرجّعه: شكله تغيّر من بعدها.",
                    "en": "I couldn't put it back: it seems to have changed since."},
    "undo_done": {"ar": "رجّعته زي ما كان ✅ {names}", "en": "Put back as it was ✅ {names}"},
    # Devices, scenes and the world (`tools_world`).
    "device_on": {"ar": "شغّلت {label} ✨", "en": "Turned on {label} ✨"},
    "device_off": {"ar": "طفّيت {label}", "en": "Turned off {label}"},
    "device_open": {"ar": "فتحت {label}", "en": "Opened {label}"},
    "device_close": {"ar": "سكّرت {label}", "en": "Closed {label}"},
    "device_level": {"ar": "ضبطت {label} على {value}", "en": "Set {label} to {value}"},
    "device_set": {"ar": "ضبطت {label}: {value}", "en": "Set {label}: {value}"},
    "device_offline": {"ar": "{label} مش متّصل هلّق، فما بعتّله الأمر. تأكّد إنه شغّال وعلى الشبكة.",
                       "en": "{label} isn't connected right now, so I didn't send it. Make sure it's on and online."},
    "device_not_allowed": {"ar": "ما ينفع هالأمر لـ {label}. المتاح: {allowed}.",
                           "en": "{label} can't do that. It can: {allowed}."},
    "device_unsupported": {"ar": "{label} مربوط بطريقة ما عادت مدعومة، فما بقدر أوصله. احذفه من التحكّم بالتطبيق.",
                           "en": "{label} is connected in a way that's no longer supported, so I can't reach it. Remove it in the app's controls."},
    "device_not_sent": {"ar": "ما اشتغل: ما قدرت أوصّل الأمر لـ {label}. جرّب كمان شوي.",
                        "en": "That didn't work: I couldn't reach {label}. Try again in a bit."},
    "no_devices": {"ar": "ما في عندك أجهزة مضافة بعد — ضيفها من تبويب التحكّم بالتطبيق.",
                   "en": "You have no devices yet — add them in the app's controls."},
    "no_such_device": {"ar": "ما لقيت جهاز بهالاسم. أجهزتك: {names}. أي واحد تقصد؟",
                       "en": "I couldn't find a device by that name. Your devices: {names}. Which one?"},
    "device_how_much": {"ar": "ما فهمت قديش أغيّر {label}.", "en": "I didn't get how much to change {label}."},
    "scene_unknown": {"ar": "ما عرفت هاد المشهد — جرّب: دراسة، قراءة، عصف ذهني، راحة، فيلم، نوم، صباح، إطفاء.",
                      "en": "I don't know that scene — try: study, reading, brainstorm, relax, movie, sleep, morning, off."},
    "scene_not_sent": {"ar": "ما تطبّق مشهد «{label}»، ما وصل ولا جهاز.{tail}",
                       "en": "Scene «{label}» wasn't applied, no device got it.{tail}"},
    "scene_applied": {"ar": "✨ طبّقت مشهد «{label}»{tail}", "en": "✨ Applied scene «{label}»{tail}"},
    "scene_skipped": {"ar": " ما عندك {names}، فتخطّيتها.", "en": " You don't have {names}, so I skipped them."},
    "scene_offline": {"ar": " {names} مش متّصل هلّق، فتخطّيته.", "en": " {names} isn't connected right now, so I skipped it."},
    "scene_missed": {"ar": " وما وصل لـ: {names}.", "en": " It didn't reach: {names}."},
    "restore_nothing": {"ar": "ما في مشهد طبّقته قبل هيك أرجّع عنه.", "en": "There's no scene I applied to undo."},
    "restore_not_sent": {"ar": "ما قدرت أرجّع الغرفة، ما وصل ولا جهاز.{tail}",
                         "en": "I couldn't restore the room, no device got it.{tail}"},
    "restored": {"ar": "رجّعت الغرفة زي ما كانت{tail}", "en": "The room is back as it was{tail}"},
    "weather_no_city": {"ar": "ما بعرف وين ساكن. بأي مدينة بدك الطقس؟",
                        "en": "I don't know where you live. Which city's weather?"},
    "weather_failed": {"ar": "ما قدرت أجيب بيانات الطقس لـ {city} حالياً.",
                       "en": "I couldn't get the weather for {city} right now."},
    "image_one_at_a_time": {"ar": "برسم صورة وحدة بكل مرة. هي الأولى جاهزة، اطلب التانية بعدها.",
                            "en": "I draw one picture at a time. The first is ready, ask for the next after it."},
    "image_failed": {"ar": "ما قدرت أولد الصورة حاليًا. جرّب تغيّر الوصف شوي أو أعد المحاولة.",
                     "en": "I couldn't make the picture right now. Try changing the description a little, or again."},
    "image_done": {"ar": "جهزت الصورة.", "en": "Your picture is ready."},
    # Outside a reply, in the user's own language (`for_user`).
    "push_title": {"ar": "ساندي", "en": "Sandy"},
    "limit_rate_limited": {"ar": "شوي شوي 😄 وصلت للحد بهالدقيقة — جرّب بعد شوي.",
                           "en": "Easy 😄 you've hit this minute's limit — try again in a moment."},
    "limit_daily_quota_exceeded": {"ar": "خلص رصيدك لليوم. بيرجع بكرا، أو رقّي اشتراكك.",
                                   "en": "You've used today's allowance. It comes back tomorrow, or upgrade your plan."},
    "limit_call_minutes_exceeded": {"ar": "خلصت دقايق الحكي لليوم. بترجع بكرا، أو رقّي اشتراكك.",
                                    "en": "You've used today's call minutes. They come back tomorrow, or upgrade your plan."},
    "limit_other": {"ar": "وصلت للحد المسموح — جرّب لاحقاً.", "en": "You've hit the limit — try again later."},
    "nudge_q_unwind": {"ar": "شو أكتر إشي بيريّحك بعد يوم طويل؟", "en": "What helps you unwind most after a long day?"},
    "nudge_q_peak": {"ar": "إنت أنشط الصبح ولا الليل؟", "en": "Are you sharper in the morning or at night?"},
    "nudge_q_procrastinate": {"ar": "شو الإشي اللي دايماً بتأجّله وودّك تخلّصه؟",
                              "en": "What do you always put off but wish you'd get done?"},
    "nudge_q_important_person": {"ar": "مين أهم شخص ما بدك تنسى مناسباته؟",
                                 "en": "Whose special days do you never want to forget?"},
    "nudge_q_one_reminder": {"ar": "لو بذكّرك بإشي وحيد كل يوم، شو بدك يكون؟",
                             "en": "If I reminded you of just one thing every day, what would it be?"},
    "nudge_q_hobby": {"ar": "شو هوايتك اللي نفسك ترجعلها؟", "en": "Which hobby would you love to get back to?"},
    "nudge_greet": {"ar": "صباح الخير 🌤️", "en": "Good morning 🌤️"},
    "nudge_greet_late": {"ar": "صباح الخير 🌙 كيفك بعد السهرة؟", "en": "Good morning 🌙 how are you after the late night?"},
    "nudge_free_day": {"ar": "{greet} يومك فاضي — خليك مرتاح، وإذا حابب نخطّط لبكرا؟",
                       "en": "{greet} Your day is free — take it easy, or shall we plan tomorrow?"},
    "nudge_your_tasks": {"ar": "مهامك", "en": "your tasks"},
    "nudge_heavy": {"ar": "يومك مضغوط شوي، بلاش تقاعس 💪", "en": "Your day is a bit packed, don't slack off 💪"},
    "nudge_light": {"ar": "يومك محتمل، خليك ماشي 🙂", "en": "Your day looks doable, keep going 🙂"},
    "nudge_day": {"ar": "{greet} {tone} عندك اليوم {tasks} مهمة و{reminders} تذكير — أهمها: {lead}.",
                  "en": "{greet} {tone} You have {tasks} tasks and {reminders} reminders today — first: {lead}."},
    "nudge_write_in": {"ar": "اكتبيه بالعربي بلهجتك.", "en": "Write it in English only."},
    "nothing_done": {"ar": "لسا ما عملت هالإشي فعلياً. احكيلي مرة تانية شو بدك بالزبط وبعمله هلّق.",
                     "en": "I haven't actually done that yet. Tell me once more exactly what you "
                           "want and I'll do it now."},
}
