"""Arabic and English are equal: the language of a turn, and every sentence the server
says itself in both.

A message with a real Arabic word (outside a quoted name) is Arabic, else one with Latin
letters is English; one with no letters at all («2», «👍»), or only a word everyone uses in both («ok»), keeps the
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
from typing import Iterator, List, Optional

AR, EN = "ar", "en"

# Arabic letters only: its punctuation («،», «؟») and digits («٢٢») name no language.
LETTERS = "ء-يٱ-ۓ"
_ARABIC = re.compile(f"[{LETTERS}]")
_LATIN = re.compile(r"[A-Za-z]")
# A name the message quotes: «حليب», "milk", “milk”.
_QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")
_current: ContextVar[str] = ContextVar("sandy_lang", default=AR)
# Inside `naming`: every value a phrase was filled with (a device's label, a row's text).
_named: ContextVar[Optional[List[str]]] = ContextVar("sandy_named", default=None)
# Slots that hold the model's own words (a web summary), never a name.
_MODEL_WORDS = {"body"}
# Said the same in Arabic and English chats: they name no language.
_BOTH_LANGUAGES = {"ok", "okay", "k", "kk"}


def of(text: str, fallback: Optional[str] = None) -> str:
    """The language a text is written in; ``fallback`` (else Arabic) when it has no letters.

    A real Arabic word (outside a quoted name) makes it Arabic, however long the English
    name or term beside it («ضيفي Nescafe Gold Blend»); an English message may quote an
    Arabic name («add «حليب» to my list»)."""
    text = text or ""
    plain = _QUOTED.sub(" ", text)
    if _ARABIC.search(plain):
        return AR
    if not _LATIN.search(plain):
        # Nothing but a quoted name, or no letters at all.
        return AR if _ARABIC.search(text) else (EN if _LATIN.search(text) else fallback or AR)
    if re.sub(r"[^a-z]", "", plain.lower()) in _BOTH_LANGUAGES:
        return fallback or AR
    return EN


@contextmanager
def using(language: str) -> Iterator[str]:
    token = _current.set(EN if language == EN else AR)
    try:
        yield _current.get()
    finally:
        _current.reset(token)


@contextmanager
def naming() -> Iterator[List[str]]:
    """The names said in it: what `say` filled a phrase with, which a right reply may hold in
    the other script (`language_guard.names_of`). The model's own words are not among them."""
    token = _named.set([])
    try:
        yield _named.get()
    finally:
        _named.reset(token)


def named() -> List[str]:
    """The names said so far inside `naming` (none outside it)."""
    return list(_named.get() or ())


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
    """The phrase in the turn's language, its slots filled (the names among them kept, see
    `naming`)."""
    named = _named.get()
    if named is not None:
        named += [v for k, v in slots.items() if isinstance(v, str) and k not in _MODEL_WORDS]
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
    # The call (`brain/voice.py`, `voice_ws`): what the live model reads back from a tool,
    # tagged when it did not happen (`[failed]`, `[not done]`), in the speaker's language.
    "voice_failed": {"ar": "[فشل التنفيذ] {text}", "en": "[failed] {text}"},
    "voice_tool_broke": {"ar": "الأداة ما اشتغلت.", "en": "The tool didn't work."},
    "voice_tool_failed": {"ar": "[فشل التنفيذ] ما قدرت أنفّذ {name}.", "en": "[failed] I couldn't run {name}."},
    "voice_not_done": {"ar": "[لم يُنفَّذ] {text}", "en": "[not done] {text}"},
    "voice_nothing_held": {"ar": "ما في إشي مستني تأكيد.", "en": "Nothing is waiting for a yes."},
    "voice_unclear_twice": {"ar": "[لم يُنفَّذ] ما فهمت جوابه مرتين، فما عملت: {summary}.",
                            "en": "[not done] Their answer wasn't clear twice, so I didn't {summary}."},
    "voice_ask_again": {"ar": "ما فهمت اه ولا لأ — اسأليه مرة تانية: {question}",
                        "en": "It wasn't clear if that was a yes or a no — ask once more: {question}"},
    "voice_unclear_pick_twice": {"ar": "[لم يُنفَّذ] ما فهمت أي وحدة مرتين، فما عملت إشي.",
                                 "en": "[not done] Which one wasn't clear twice, so nothing was done."},
    "voice_ask_pick_again": {"ar": "ما فهمت أي وحدة — اسأليه مرة تانية:\n{question}",
                             "en": "It wasn't clear which one — ask once more:\n{question}"},
    "voice_said_more": {"ar": "قال كمان إشي بعد جوابه: نفّذيه هلأ.",
                        "en": "They asked for more after the answer: do it now."},
    "voice_said_more_pick": {"ar": "قال كمان إشي بعد اختياره: نفّذيه هلأ.",
                             "en": "They asked for more after choosing: do it now."},
    "voice_still_waiting": {"ar": "لسا ما نفّذت — اسأليه:\n{question}",
                            "en": "Not done yet — ask them:\n{question}"},
    "voice_gate_not_ready": {"ar": "[لم يُنفَّذ] التحقق من الصوت مش جاهز هلّق. لا تنفّذي الأمر — قولي "
                                   "إنك مش قادرة تتأكدي من صوته هلّق، وخلّيه يجرّب كمان شوي.",
                             "en": "[not done] Voice checking isn't ready right now. Don't run it — say "
                                   "you can't confirm their voice right now, and to try again shortly."},
    "voice_gate_refused": {"ar": "ما قدرت أتأكد إنه صوتك. لا تنفّذي الأمر — اسألي بلطف: مين معي؟",
                           "en": "I couldn't confirm it's their voice. Don't run it — kindly ask who is speaking."},
    # The honesty check on the call: what she is told when she said she did what no tool did.
    "voice_correction": {"ar": "[تنبيه من النظام، مش من المستخدم: قلتي إنك {what} بس ما في أداة نفّذت "
                               "هالإشي بهالدور، يعني ما انعمل. صحّحي حالك هلّق بجملة قصيرة: قوليله "
                               "إنه ما انعمل لسا، واسأليه إذا بدّه تعمليه، أو نفّذيه بالأداة إذا طلبه.]",
                         "en": "[A note from the system, not the user: you said you {what}, but no tool "
                               "did that in this turn, so it did not happen. Put it right now in one "
                               "short sentence: tell them it isn't done yet and ask if they want it, or "
                               "do it with the tool if they asked.]"},
    "said_delete": {"ar": "حذفتي", "en": "deleted it"},
    "said_cancel": {"ar": "لغيتي", "en": "cancelled it"},
    "said_edit": {"ar": "عدّلتي", "en": "changed it"},
    "said_add": {"ar": "ضفتي", "en": "added it"},
    "said_done": {"ar": "خلّصتي", "en": "did it"},
    # A route's own words (`api/`), and a row's: in the user's language (`require_auth`).
    "file_missing": {"ar": "ما وصلني الملف.", "en": "The file didn't reach me."},
    "file_too_big_image": {"ar": "الصورة أكبر من ثمانية ميغا. صغّرها أو اختار وحدة تانية.",
                           "en": "The picture is over eight megabytes. Make it smaller or pick another."},
    "file_too_big": {"ar": "الملف أكبر من خمسة ميغا. ابعت ملف أصغر أو جزء منه.",
                     "en": "The file is over five megabytes. Send a smaller one, or part of it."},
    "file_unsupported": {"ar": "ما بقدر أقرأ هالنوع. ابعت صورة، أو PDF، أو Word، أو ملف نص.",
                         "en": "I can't read that kind of file. Send a picture, a PDF, a Word file or a text file."},
    "file_unreadable": {"ar": "ما قدرت أطلع نص من هالملف. ممكن يكون صور بس أو محمي.",
                        "en": "I couldn't get any text out of that file. It may be only pictures, or protected."},
    "file_too_big_unpacked": {"ar": "هالملف بيكبر كتير لما ينفتح، ما بقدر أقراه. ابعت جزء منه.",
                              "en": "That file grows too big when opened, so I can't read it. Send part of it."},
    "attachment_not_saved": {"ar": "ما قدرت أحفظ المرفق هلّق، جرّب كمان شوي.",
                             "en": "I couldn't save the attachment right now, try again in a bit."},
    "weather_pick_city": {"ar": "اختار مدينتك عشان أجيبلك الطقس.", "en": "Pick your city so I can get the weather."},
    "still_answering": {"ar": "ساندي لسا عم تجاوب على هالرسالة، لحظة.",
                        "en": "Sandy is still answering this message, one moment."},
    "still_stopping": {"ar": "لسا عم خلّص الرد اللي وقّفته، جرّب كمان شوي.",
                       "en": "I'm still finishing the reply you stopped, try again in a bit."},
    "image_needs_both": {"ar": "لازم وصف وصورة مع بعض.", "en": "I need both a description and a picture."},
    "image_edit_failed": {"ar": "ما قدرت أعدّل الصورة هلّق. جرّب كمان شوي.",
                          "en": "I couldn't edit the picture right now. Try again in a bit."},
    "image_read_failed": {"ar": "ما قدرت أحلل الصورة هلّق. جرّب كمان شوي.",
                          "en": "I couldn't read the picture right now. Try again in a bit."},
    "voice_id_off": {"ar": "تمييز الصوت مش مفعّل على السيرفر.", "en": "Voice recognition isn't on for this server."},
    "bad_number": {"ar": "«{name}» لازم يكون رقم من واحد لـ {top}.", "en": "«{name}» must be a number from 1 to {top}."},
    "time_format": {"ar": "الوقت لازم يكون بصيغة ساعة ودقيقة.", "en": "The time must be in hours and minutes."},
    "note_empty": {"ar": "اكتب ملاحظتك أول.", "en": "Write your note first."},
    "not_saved": {"ar": "ما وصلت، جرّب كمان شوي.", "en": "That didn't go through, try again in a bit."},
    "account_partial_reset": {"ar": "ما انمسح كل شي، في جزء ضل. جرّب كمان مرّة وبكمّل من وين وقفت.",
                              "en": "Not everything was erased, some is left. Try again and I'll carry on from where I stopped."},
    "account_partial_delete": {"ar": "ما انحذف كل شي، في جزء ضل وحسابك لسا موجود. سجّل دخولك من جديد "
                                     "وجرّب الحذف كمان مرّة، وبكمّل من وين وقفت.",
                               "en": "Not everything was deleted, some is left and your account still exists. "
                                     "Sign in again and delete once more, and I'll carry on from where I stopped."},
    "account_unavailable": {"ar": "ما قدرت أحذف الحساب هلق، وما انمسح ولا شي. جرّب كمان شوي.",
                            "en": "I couldn't delete the account right now, and nothing was erased. Try again in a bit."},
    "summary_empty": {"ar": "ما في إشي مسجّل بهالفترة.", "en": "There's nothing logged in that period."},
    "sealed_message": {"ar": "(رسالة مختومة لحد موعدها)", "en": "(sealed until its time)"},
    "new_chat": {"ar": "محادثة جديدة", "en": "New chat"},
    "chat_untitled": {"ar": "محادثة", "en": "Chat"},
    "photo_title": {"ar": "صورة {when}", "en": "Photo {when}"},
    "demo_web_title": {"ar": "نتيجة بحث تجريبية", "en": "A sample search result"},
    "demo_web_text": {"ar": "هذه نتيجة تجريبية — سجّل دخولك ليبحث ساندي فعلياً على الويب.",
                      "en": "This is a sample result — sign in for Sandy to really search the web."},
    "demo_place_name": {"ar": "مقهى تجريبي", "en": "A sample café"},
    "demo_place_address": {"ar": "وسط البلد", "en": "Downtown"},
    "demo_place_price": {"ar": "متوسط", "en": "Moderate"},
    "demo_place_open": {"ar": "مفتوح الآن", "en": "Open now"},
    "research_no_service": {"ar": "ما قدرت أكمل البحث — خدمة البحث غير متوفرة حالياً.",
                            "en": "I couldn't search — the search service isn't available right now."},
    "research_error": {"ar": "ما قدرت أجد نتائج عن '{query}' — خطأ في الاتصال بخدمة البحث.",
                       "en": "I couldn't find results for '{query}' — the search service didn't answer."},
    "research_none": {"ar": "ما قدرت أجد نتائج عن '{query}' الآن. جرب مرة ثانية لاحقاً.",
                      "en": "I couldn't find results for '{query}' right now. Try again later."},
    "research_unclear": {"ar": "ما قدرت أجد نتائج واضحة عن '{query}'.",
                         "en": "I couldn't find clear results for '{query}'."},
    # Tasks (`brain/task_runner.py`, `brain/tools_tasks.py`).
    "task_confirm": {"ar": "أتابع «{title}» {every}، وأبلّغك بس إذا في جديد",
                     "en": "follow «{title}» {every}, and tell you only when there is something new"},
    "task_saved": {"ar": "تمام، بتابع «{title}» {every} ✅", "en": "Done, I'll follow «{title}» {every} ✅"},
    "task_forbidden": {"ar": "المهمة بتقرا وبتبلّغ بس: ما بتدفع ولا بتبعت باسمك ولا بتنشر ولا بتحذف.",
                       "en": "A task only reads and tells you: it never pays, sends in your name, publishes or deletes."},
    "task_none": {"ar": "ما في مهام شغّالة.", "en": "No tasks are running."},
    "task_row": {"ar": "«{title}» {every}", "en": "«{title}» {every}"},
    "task_row_paused": {"ar": "«{title}» {every} (موقّفة)", "en": "«{title}» {every} (paused)"},
    "task_paused": {"ar": "وقّفت «{title}» ⏸", "en": "Paused «{title}» ⏸"},
    "task_resumed": {"ar": "رجّعت «{title}» ▶️", "en": "«{title}» is running again ▶️"},
    "task_every": {"ar": "صارت «{title}» {every}", "en": "«{title}» now runs {every}"},
    "task_removed": {"ar": "شلت مهمة «{title}» ✅", "en": "Removed the task «{title}» ✅"},
    "task_not_found": {"ar": "ما لقيت مهمة بهالاسم.", "en": "I couldn't find a task by that name."},
    "every_minutes": {"ar": "كل {n} دقيقة", "en": "every {n} minutes"},
    "every_hours": {"ar": "كل {n} ساعة", "en": "every {n} hours"},
    "task_stopped": {"ar": "وقّفت مهمة «{title}»: فشلت تلات مرات ورا بعض. خبّرني إذا بدك أرجّعها.",
                     "en": "I stopped the task «{title}»: it failed three times in a row. Tell me if you want it back."},
    "research_summary": {"ar": "📌 الملخص:\n{body}", "en": "📌 Summary:\n{body}"},
    "research_sources": {"ar": "📎 المصادر:", "en": "📎 Sources:"},
    "research_no_summary": {"ar": "ما قدرت ألخص النتائج بشكل واضح حالياً.",
                            "en": "I couldn't sum up the results clearly right now."},
    "file_cut": {"ar": "[… الملف أطول من هيك، هاد أول جزء منه بس]",
                 "en": "[… the file is longer than this; this is only its first part]"},
    "weather_unavailable": {"ar": "الطقس: غير متوفر حالياً", "en": "Weather: not available right now"},
    "weather_report": {"ar": "الطقس في {city} اليوم: {description}، الحرارة {temp}°C (الشعور الفعلي "
                             "{feels}°C)، أعلى {high}°C وأدنى {low}°C، الرطوبة {humidity}%، "
                             "الغروب الساعة {sunset}",
                       "en": "Weather in {city} today: {description}, {temp}°C (feels like "
                             "{feels}°C), high {high}°C and low {low}°C, humidity {humidity}%, "
                             "sunset at {sunset}"},
    "place_open": {"ar": "مفتوح الآن", "en": "Open now"},
    "place_closed": {"ar": "مغلق الآن", "en": "Closed now"},
    "price_1": {"ar": "رخيص", "en": "Inexpensive"},
    "price_2": {"ar": "متوسط", "en": "Moderate"},
    "price_3": {"ar": "غالي", "en": "Expensive"},
    "price_4": {"ar": "فاخر", "en": "Very expensive"},
    "enroll_cancelled": {"ar": "أُلغي التسجيل.", "en": "Enrollment cancelled."},
    "enroll_unavailable": {"ar": "تمييز الصوت غير مفعّل (مكتبة sherpa-onnx ناقصة).",
                           "en": "Voice recognition is off (the sherpa-onnx library is missing)."},
    "enroll_nothing": {"ar": "ما وصلني أي تسجيل.", "en": "No recording reached me."},
    "enroll_no_model": {"ar": "ما قدرت أجهّز نموذج الصوت (تنزيل/تحميل فشل).",
                        "en": "I couldn't set up the voice model (it failed to download or load)."},
    "enroll_unclear": {"ar": "التسجيلات قصيرة أو مش واضحة — جرّب تسجيلات أطول وأوضح.",
                       "en": "The recordings are short or unclear — try longer, clearer ones."},
    "enroll_broken": {"ar": "صار خلل ببناء البصمة.", "en": "Something went wrong building the voiceprint."},
    "enroll_not_saved": {"ar": "ما قدرت أحفظ بصمة صوتك بأمان هلق — جرّب بعدين.",
                         "en": "I couldn't save your voiceprint safely right now — try later."},
    "enroll_done": {"ar": "تمام! صرت أعرف صوتك ✅ ({n} مقاطع)", "en": "Done! I know your voice now ✅ ({n} clips)"},
    "voice_end_call": {"ar": "تمام: المكالمة بتسكّر بعد هالجملة. ودّعيه بكلمة قصيرة وبس.",
                       "en": "OK: the call ends after this sentence. Say a short goodbye, nothing more."},
    "nothing_done": {"ar": "لسا ما عملت هالإشي فعلياً. احكيلي مرة تانية شو بدك بالزبط وبعمله هلّق.",
                     "en": "I haven't actually done that yet. Tell me once more exactly what you "
                           "want and I'll do it now."},
}
