"""Arabic and English are equal: every sentence the server says itself (not the model's)
comes in the language of the message it answers."""
from __future__ import annotations

from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.brain import lang, loop
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             complete=model)


def test_a_message_is_read_as_english_or_arabic():
    assert lang.of("remind me at 5") == "en"
    assert lang.of("ذكريني بالـ meeting") == "ar"
    assert lang.of("2") == "ar" and lang.of("2", fallback="en") == "en"
    assert lang.of("ok") == "ar" and lang.of("OK!", fallback="en") == "en"
    assert lang.of("ok thanks") == "en"


def test_a_phrase_comes_in_the_turns_language():
    with lang.using("en"):
        assert lang.say("error") == "Something went wrong, please try again."
    with lang.using("ar"):
        assert lang.say("error") == "حصل خطأ، حاول مرة ثانية."


def test_every_phrase_has_both_languages_with_the_same_slots():
    import string
    for key, versions in lang.PHRASES.items():
        assert set(versions) == {"ar", "en"}, key
        slots = [{f for _, f, _, _ in string.Formatter().parse(v) if f} for v in versions.values()]
        assert slots[0] == slots[1], key


def test_a_failed_model_answers_in_the_messages_language(brain_db):  # noqa: F811
    class Down:
        def __call__(self, messages, specs, on_text=None):
            return None
    assert _turn(Down(), "add milk please")["final_response"] == lang.PHRASES["error"]["en"]
    assert _turn(Down(), "ضيفي حليب")["final_response"] == lang.PHRASES["error"]["ar"]


def test_a_reply_with_no_letters_follows_the_conversation(brain_db):  # noqa: F811
    _turn(ScriptedModel(text_reply("Sure.")), "hello there")

    class Down:
        def __call__(self, messages, specs, on_text=None):
            return None
    assert _turn(Down(), "2")["final_response"] == lang.PHRASES["error"]["en"]


# ── the honesty check reads English claims as it reads Arabic ones ──────────

def test_english_claims_are_read():
    from app.brain import honesty
    assert honesty.claims("I deleted the milk.") == {"delete"}
    assert honesty.claims("Removed it from your list") == {"delete"}
    assert honesty.claims("Added eggs ✅") == {"add"}
    assert honesty.claims("I've cancelled the reminder.") == {"cancel"}
    assert honesty.claims("Updated your task.") == {"edit"}
    assert honesty.claims("Done!") == {"done"}


def test_english_negations_and_futures_are_not_claims():
    from app.brain import honesty
    for text in ("I haven't deleted anything yet.", "It was not added.", "I didn't remove it.",
                 "It will be deleted once you say yes.", "Do you want it to be added?",
                 "Nothing was cancelled."):
        assert honesty.claims(text) == set(), text


def test_done_is_backed_by_any_tool_that_worked():
    from app.brain import honesty
    assert honesty.unbacked("Done!", []) == {"done"}
    assert honesty.unbacked("Done!", ["device_control"]) == set()
    assert honesty.unbacked("تم ✅", []) == {"done"}


def test_an_english_reply_that_lies_is_answered_in_english():
    from app.brain import honesty
    with lang.using("en"):
        out = honesty.correct("I deleted the milk.", [], [])
    assert out == lang.PHRASES["nothing_done"]["en"]
    with lang.using("ar"):
        assert honesty.correct("حذفت الحليب.", [], []) == lang.PHRASES["nothing_done"]["ar"]


# ── a held question is answered in English as in Arabic ─────────────────────

def test_english_yes_and_no():
    from app.brain import confirm
    held = {"summary": "delete «milk»"}
    for yes in ("yes", "yeah", "sure", "go ahead", "do it", "yes please", "ok go ahead",
                "absolutely", "of course", "yes delete it", "delete it", "alright"):
        assert confirm.answer(yes, held) == "yes", yes
    for no in ("no", "nope", "cancel", "never mind", "no thanks", "don't", "don't delete it",
               "leave it", "forget it", "no wait"):
        assert confirm.answer(no, held) == "no", no
    assert confirm.read("yes and add bread", held) == ("yes", True)


def test_english_picks():
    from app.brain import confirm
    rows = [{"id": "a", "text": "milk"}, {"id": "b", "text": "bread"}, {"id": "c", "text": "eggs"}]
    assert confirm.pick("the first one", rows) == (["a"], False)
    assert confirm.pick("second", rows) == (["b"], False)
    assert confirm.pick("the last one", rows) == (["c"], False)
    assert confirm.pick("first and third", rows) == (["a", "c"], False)
    assert confirm.pick("all of them", rows) == (["a", "b", "c"], False)
    assert confirm.pick("number 2", rows) == (["b"], False)
    assert confirm.pick("both", rows[:2]) == (["a", "b"], False)


def test_the_questions_come_in_the_turns_language():
    from app.brain import confirm
    rows = [{"id": "a", "text": "milk"}, {"id": "b", "text": "bread"}]
    with lang.using("en"):
        assert confirm.question("delete «milk»") == "Are you sure you want to delete «milk»? (yes/no)"
        q = confirm.choice_question(rows)
        assert q.startswith("I found more than one:") and "1. milk" in q and "Which one?" in q
        assert lang.say("cancelled") == "OK, I didn't do anything."
    with lang.using("ar"):
        assert confirm.question("تحذف «حليب»") == "متأكد إنك بدك تحذف «حليب»؟ (اه/لأ)"
        assert confirm.choice_question(rows).startswith("لقيت أكتر من وحدة:")


# ── the tools' own replies come in the turn's language ──────────────────────

def _run(name, **args):
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    with active_user_profile_context(A):
        return tools.execute(name, args, TurnCtx(user_id="userA"))


def test_a_list_reply_comes_in_english(brain_db):  # noqa: F811
    with lang.using("en"):
        assert _run("list_add", list="shopping", text="milk")["reply"] == "Added «milk» ✅"
        assert _run("list_add", list="shopping", text="milk")["reply"] == "«milk» is already on the list"
        assert _run("list_delete", list="shopping", match_text="milk")["reply"] == "Deleted «milk» ✅"
        assert _run("list_delete", list="shopping", match_text="bread")["reply"].startswith(
            "I couldn't find «bread»")
    with lang.using("ar"):
        assert _run("list_add", list="shopping", text="حليب")["reply"] == "ضفت «حليب» ✅"


def test_a_bulk_delete_asks_in_english(brain_db):  # noqa: F811
    for t in ("a1", "b2", "c3", "d4", "e5", "f6"):
        _run("list_add", list="shopping", text=t)
    with lang.using("en"):
        r = _run("list_delete", list="shopping", everything=True)
        from app.brain import confirm
        assert r["needs_confirmation"] and confirm.question(r["summary"]).startswith(
            "Are you sure you want to delete «a1», «b2», «c3» and 3 more?")
        assert confirm.answer("yes", {"summary": r["summary"]}) == "yes"


def test_a_device_reply_comes_in_english(brain_db, monkeypatch):  # noqa: F811
    from types import SimpleNamespace as NS

    from brain_fakes import on_node

    from app.features import device_store
    monkeypatch.setattr("app.integrations.device_publisher.get_device_publisher",
                        lambda: NS(send_to_topic=lambda topic, payload: True))
    with active_user_profile_context(A):
        device_store.add_device("lamp", "Lamp", "switch", on_node("lamp"))
    with lang.using("en"):
        assert _run("device_control", device="lamp", action="on")["reply"] == "Turned on Lamp ✨"
        assert _run("device_control", device="nothing", action="on")["reply"].startswith(
            "I couldn't find a device by that name.")


def test_nothing_the_server_says_is_written_in_one_language_only():
    """What the user reads (a reply, a route's message or error, a tool's output to the live
    model, a row's text) is a phrase in both languages (`lang.PHRASES`), never a literal,
    anywhere in cloud/app. A prompt or note only the model reads stays in one language
    (`lang` docstring), so `Part(text=…)` and system messages are not read here.
    Arabic and English alike: a field the user reads may hold neither as a literal.

    Nor may a function give back or set aside Arabic it did not take from a phrase («text = …
    + "[… الملف أطول]"», «body or "ما قدرت ألخص"»): only the field and the module-constant
    checks ran until 29 Oct 2026, and a sentence put together inside a function slipped past
    both. A function that writes what the model alone reads is named in `_PROMPT_FUNCTIONS`."""
    import ast
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "cloud" / "app"
    keys = {"reply", "message", "error", "title", "body", "text", "output", "detail", "msg",
            "caption", "name", "address", "price_level", "open_now"}
    arabic = re.compile(r"[ء-ي]")

    def said(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return bool(arabic.search(node.value))
        if isinstance(node, ast.JoinedStr):
            return any(said(v) for v in node.values)
        if isinstance(node, (ast.BinOp, ast.IfExp, ast.BoolOp)):
            return any(said(v) for v in ast.iter_child_nodes(node))
        return False

    english = re.compile(r"[A-Za-z]+ [A-Za-z]+ [A-Za-z]+")

    def sentence(node):
        return isinstance(node, ast.Constant) and isinstance(node.value, str) \
            and bool(english.search(node.value))

    found = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "lang.py":
            continue
        where = str(path.relative_to(root))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                found += [f"{where}:{v.lineno} {k.value}"
                          for k, v in zip(node.keys, node.values)
                          if isinstance(k, ast.Constant) and k.value in keys and v is not None
                          and (said(v) or sentence(v))]
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AttachmentError":
                found += [f"{where}:{node.lineno} AttachmentError" for a in node.args if said(a)]
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and fn.name not in _PROMPT_FUNCTIONS.get(where, set()):
                found += [f"{where}:{node.lineno} {fn.name}" for node in ast.walk(fn)
                          if isinstance(node, (ast.Assign, ast.AugAssign, ast.Return))
                          and node.value is not None and said(node.value)]
        # A constant at the top of a module is a prompt the model reads, named here; anything
        # else in Arabic there is something said, and belongs in `lang.PHRASES`.
        for node in tree.body:
            if isinstance(node, ast.Assign) and said(node.value):
                names = {t.id for t in node.targets if isinstance(t, ast.Name)}
                if not names <= _PROMPTS.get(where, set()):
                    found.append(f"{where}:{node.lineno} {sorted(names)}")
    assert not found, found


# The model reads these, never the user (`lang`: what the model reads stays in one language).
_PROMPTS = {
    "api/daily_nudge_api.py": {"_AGENDA_INSTRUCTION"},
    "api/voice_ws/memory.py": {"_END_CALL_ROBOT", "_END_CALL_APP"},
    "api/voice_ws/session.py": {"_APP_CHANNEL", "_ROBOT_CHANNEL", "_UNHEARD_QUESTION"},
    "api/voice_ws/tools.py": {"_PAST_RECORD_NOTE", "_DEVICE_SCENE_RULES"},
    "brain/context.py": {"_RULES", "CHAT_CHANNEL", "SPOKEN_CHANNEL", "TOOL_WORDS_RULE"},
    "brain/loop.py": {"HELD_NOTE"},
    "brain/persona.py": {"_ANTI_INJECTION", "LANGUAGE_RULE", "NO_PROMISES_RULE"},
    "brain/stm.py": {"_SUMMARY_PROMPT"},
    "brain/stops.py": {"CUT_NOTE"},
    "brain/tools_blocks.py": {"_ASK_TIME"},
    "features/research.py": {"_SUMMARY_SYSTEM"},
    "features/vision.py": {"_VISION_CONTEXT"},
    "utils/user_profiles.py": {"HAS_NO_NAME"},
}


# Functions that write what the model alone reads: notes, context lines, tool descriptions.
_PROMPT_FUNCTIONS = {
    "api/daily_nudge_api.py": {"_generate_agenda"},
    "api/voice_ws/memory.py": {"_channel_line", "_load_stm_context", "get_voice_channel",
                               "session_context"},
    "api/voice_ws/speaker.py": {"_learn_voice", "_speaker_directive"},
    "api/voice_ws/tools.py": {"_system_instruction_body"},
    "brain/context.py": {"devices_line", "facts_block", "profile_block", "reply_language",
                         "state_block"},
    "brain/loop.py": {"_resolve_pending", "_rest_note", "_user_content"},
    "brain/tools.py": {"_list_enum"},
    "brain/tools_blocks.py": {"budget_note"},
    "features/photo_album.py": {"generate_tags"},
    "utils/time_awareness.py": {"ago_ar", "last_contact_line", "now_line",
                                "time_awareness_block", "when_ar"},
    "utils/user_profiles.py": {"address_instruction"},
}


# ── the fallback time reader reads English as it reads Arabic ───────────────

import pytest  # noqa: E402

from app.brain import when as W  # noqa: E402
from app.utils.time import USER_TZ  # noqa: E402


def _clock(text):
    from datetime import datetime
    sat_10am = datetime(2026, 10, 3, 10, 0, tzinfo=USER_TZ)
    at = W._clock(text, sat_10am)
    return at.astimezone(USER_TZ).strftime("%Y-%m-%d %H:%M") if at else None


@pytest.mark.parametrize("text,want", [
    ("tomorrow at 5", "2026-10-04 17:00"),
    ("tomorrow at 5 pm", "2026-10-04 17:00"),
    ("at 9am", "2026-10-04 09:00"),
    ("5:30 pm", "2026-10-03 17:30"),
    ("friday at 5", "2026-10-09 17:00"),
    ("monday at 9 in the morning", "2026-10-05 09:00"),
    ("tonight at 10", "2026-10-03 22:00"),
    ("at 12 noon", "2026-10-03 12:00"),
    ("at 12 at night", "2026-10-04 00:00"),
    ("today at 5", "2026-10-03 17:00"),
])
def test_english_clock_words(text, want):
    assert _clock(text) == want


def test_an_english_relative_time_is_left_to_minutes_as_an_arabic_one_is():
    assert _clock("in an hour") is None and _clock("in 30 minutes") is None
    assert _clock("بعد ساعة") is None


@pytest.mark.parametrize("text", ["in 2 days", "tomorrow", "next week"])
def test_english_days_without_a_clock(text):
    from app.utils.arabic_days import parse_date_from_text
    assert parse_date_from_text(text) is not None


@pytest.mark.parametrize("said,rule", [
    ("every monday", "FREQ=WEEKLY;BYDAY=MO"), ("every Friday", "FREQ=WEEKLY;BYDAY=FR"),
    ("كل اتنين", "FREQ=WEEKLY;BYDAY=MO"), ("كل جمعة", "FREQ=WEEKLY;BYDAY=FR"),
    ("every day", "FREQ=DAILY"), ("كل يوم", "FREQ=DAILY"),
    ("every week", "FREQ=WEEKLY"), ("كل شهر", "FREQ=MONTHLY"),
])
def test_a_spoken_repeat_is_a_rule(said, rule):
    assert W.recurrence_rule(said) == rule


def test_the_rules_name_the_english_way_of_saying_each_thing():
    """The model is shown how each thing is said in English too, not in Arabic only."""
    from app.brain import context
    for phrase in ("undo", "bring it back", "delete", "remove", "remind me", "I need to",
                   "set up the room", "yes", "every Monday"):
        assert phrase in context._RULES, phrase


@pytest.mark.parametrize("mood,arabic,english", [
    ("sad", "للأسف ما زبط", "Unfortunately that didn't work"),
    ("worried", "دير بالك عالطريق", "Watch out on the road"),
    ("love", "بحبك كتير", "I love you too"),
    ("big_happy", "ألف مبروك!", "Congratulations!"),
    ("proud", "برافو عليك", "Great job on that"),
    ("surprised", "عن جد؟", "No way!"),
    ("playful", "ههههه", "hahaha"),
    ("grateful", "شكراً إلك", "Thanks a lot"),
    ("confused", "ما فهمت عليك", "I didn't understand that"),
    ("thinking", "لحظة خليني أشوف", "Hold on, let me look"),
    ("excited", "يلا نبلّش", "Let's do this"),
])
def test_her_face_reads_english_as_arabic(mood, arabic, english):
    from app.api.voice_ws import face
    assert face.mood_of(arabic) == mood and face.mood_of(english) == mood


def test_an_english_reply_is_told_to_carry_no_arabic_endearment():
    from app.brain import context, persona
    line = context.reply_language("add milk please")
    assert "endearment" in line and "English" in line
    assert "dear" in persona.LANGUAGE_RULE


# ── a reply in the wrong language is put into the message's ─────────────────

def test_an_arabic_reply_to_an_english_message_is_rewritten_in_english(brain_db):  # noqa: F811
    model = ScriptedModel(text_reply("تمام، رح أذكّرك بكرا ⏰"), text_reply("OK, I'll remind you tomorrow ⏰"))
    state = _turn(model, "remind me tomorrow please")
    assert state["final_response"] == "OK, I'll remind you tomorrow ⏰"
    assert "English" in model.seen[1][0]["content"]
    assert model.seen[1][-1]["content"].endswith("تمام، رح أذكّرك بكرا ⏰")


def test_an_english_reply_to_an_arabic_message_is_rewritten_in_arabic(brain_db):  # noqa: F811
    model = ScriptedModel(text_reply("Sure, I can help with that."), text_reply("أكيد، بساعدك."))
    assert _turn(model, "ممكن تساعدني؟")["final_response"] == "أكيد، بساعدك."


def test_a_reply_already_in_the_language_or_with_quoted_names_is_left(brain_db):  # noqa: F811
    model = ScriptedModel(text_reply("Your list has «حليب» on it."))
    assert _turn(model, "what's on my list?")["final_response"] == "Your list has «حليب» on it."
    assert len(model.seen) == 1


def test_a_rewrite_that_fails_keeps_the_reply(brain_db):  # noqa: F811
    class Once(ScriptedModel):
        def __call__(self, messages, specs, on_text=None):
            if self.seen:
                self.seen.append(messages)
                return None
            return super().__call__(messages, specs, on_text)
    state = _turn(Once(text_reply("تمام")), "hello")
    assert state["final_response"] == "تمام"


def test_wrong_language_is_read_outside_quoted_names():
    from app.brain import language_guard as G
    assert G.wrong_language("Added «حليب» ✅", "en") is False
    assert G.wrong_language("I added it, يا عيوني!", "en") is True
    assert G.wrong_language("ضفت «milk» ✅", "ar") is False
    assert G.wrong_language("Sure, I added milk.", "ar") is True


def test_the_rules_keep_tool_words_in_the_users_language():
    from app.brain import context
    assert "never translated" in context._RULES
    assert "I paid" in context._RULES


# A message with a real Arabic word is Arabic, however long the English name in it; an
# English one may quote an Arabic name (independent review, 29 Oct 2026).
@pytest.mark.parametrize("text, want", [
    ("ضيفي Nescafe Gold Blend", "ar"),
    ("شو يعني machine learning", "ar"),
    ("ذكريني بال meeting مع John Smith بكرا", "ar"),
    ("«حليب»", "ar"),
    ("add Nescafe Gold Blend to the shopping list", "en"),
    ("what does machine learning mean", "en"),
    ("add «حليب» to my list", "en"),
    ('add "خبز" please', "en"),
])
def test_a_real_arabic_word_makes_the_message_arabic(text, want):
    assert lang.of(text) == want, text


# A reply in the right language is not rewritten for a name, a brand, a link or a number in
# the other one (independent review, 29 Oct 2026).
@pytest.mark.parametrize("text, language, names", [
    ("Turned on ضو الصالة ✨", "en", ["ضو الصالة"]),
    ("Here it is: https://example.com/عربي", "en", []),
    ("Your total is ٥٠ shekels.", "en", []),
    ("Done, I told محمد.", "en", ["محمد"]),
    ("شغّلت Desk lamp ✨", "ar", ["Desk lamp"]),
    ("هاد الرابط: https://www.example.com/watch?v=abcdef", "ar", []),
    ("أحسن تلفون هلّق iPhone 15 Pro Max", "ar", []),
    ("ضفت Nescafe Gold Blend للقائمة", "ar", ["Nescafe Gold Blend"]),
])
def test_a_name_link_or_number_is_not_the_wrong_language(text, language, names):
    from app.brain import language_guard as G
    assert G.wrong_language(text, language, names) is False, text


@pytest.mark.parametrize("text, language", [
    ("I added it, يا عيوني!", "en"),
    ("Sure, I added milk to your list.", "ar"),
])
def test_the_wrong_language_is_still_caught_beside_a_name(text, language):
    from app.brain import language_guard as G
    assert G.wrong_language(text, language, ["Desk lamp", "ضو الصالة"]) is True, text


@pytest.mark.parametrize("message, label, want", [
    ("turn on the hall light", "ضو الصالة", "Turned on ضو الصالة ✨"),
    ("شغّلي الضو", "Desk lamp", "شغّلت Desk lamp ✨"),
])
def test_a_device_named_in_the_other_language_is_not_rewritten(brain_db, monkeypatch,  # noqa: F811
                                                                message, label, want):
    from types import SimpleNamespace as NS

    from brain_fakes import on_node

    from app.features import device_store
    monkeypatch.setattr("app.integrations.device_publisher.get_device_publisher",
                        lambda: NS(send_to_topic=lambda topic, payload: True))
    with active_user_profile_context(A):
        device_store.add_device("lamp", label, "switch", on_node("lamp"))
    model = ScriptedModel(tools_reply(call("device_control", device="lamp", action="on")))
    assert _turn(model, message)["final_response"] == want
    assert len(model.seen) == 1


# The rewrite is the model's too: what it claims is checked again (independent review).
@pytest.mark.parametrize("message, first, rewrite, language", [
    ("is the milk still on my list?", "لسا ما حذفت الحليب، بدك أحذفه؟", "Deleted the milk ✅", "en"),
    ("الحليب لسا بالقائمة؟", "I haven't deleted the milk yet.", "حذفت الحليب ✅", "ar"),
])
def test_a_rewrite_that_claims_a_write_is_checked_again(brain_db, message, first,  # noqa: F811
                                                        rewrite, language):
    model = ScriptedModel(text_reply(first), text_reply(rewrite))
    assert _turn(model, message)["final_response"] == lang.PHRASES["nothing_done"][language]


# What fell in English on 29 Oct 2026: «what's the weather like tomorrow?» asked for a city
# instead of calling the tool; «no, I meant 60 not 50» updated the row and deleted it in the
# same step. The tools say it in both languages.
def test_the_weather_tool_is_called_without_a_city_in_both_languages():
    from app.brain import tools
    spec = next(t for t in tools.openai_tools() if t["function"]["name"] == "weather")["function"]
    said = spec["description"] + spec["parameters"]["properties"]["city"]["description"]
    assert "ما تسألي" in said and "never ask" in said


def test_a_correction_is_one_update_never_a_delete_in_both_languages():
    from app.brain import context, tools
    spec = next(t for t in tools.openai_tools() if t["function"]["name"] == "log_update")["function"]
    assert "I meant 60 not 50" in spec["description"] and "ما تحذفي" in spec["description"]
    assert "I meant 60 not 50" in context._RULES


# «turn off the AC in an hour» was sent to the device at once, its time as a value (eval,
# 29 Oct 2026); a command with a time is a schedule, said in both languages.
def test_a_device_command_with_a_time_is_a_schedule_in_both_languages():
    from app.brain import tools
    spec = next(t for t in tools.openai_tools() if t["function"]["name"] == "device_control")["function"]
    said = spec["description"] + spec["parameters"]["properties"]["value"].get("description", "")
    assert "بعد ساعة" in said and "in an hour" in said and "schedule" in said


# «Rewrite this reply in English» came back in Arabic every time on the real model (29 Oct
# 2026): the reply is handed over as text to translate, not as a message to answer.
@pytest.mark.parametrize("message, first, head, word", [
    ("is the AC on?", "حبيبي، المكيف مطفي.", "The reply to translate:", "Translate"),
    ("المكيف شغال؟", "The AC is off.", "الرد اللي بدّه ترجمة:", "ترجمي"),
])
def test_the_rewrite_hands_the_reply_over_as_text_to_translate(brain_db, message, first,  # noqa: F811
                                                               head, word):
    model = ScriptedModel(text_reply(first), text_reply("ok"))
    _turn(model, message)
    system, user = model.seen[1][0]["content"], model.seen[1][-1]["content"]
    assert word in system and user == f"{head}\n\n{first}"


# Arabic punctuation and digits name no language: one «؟» or «٢٢» in an English message
# made the turn Arabic (review of 29 Oct 2026). Letters only, as the language check reads.
@pytest.mark.parametrize("text, want", [
    ("what time is my meeting؟", "en"),
    ("set the AC to ٢٢", "en"),
    ("ok، thanks", "en"),
    ("شو الساعة؟", "ar"),
    ("خلّيه ٢٢", "ar"),
])
def test_arabic_punctuation_and_digits_name_no_language(text, want):
    assert lang.of(text) == want, text


def test_a_message_of_arabic_digits_alone_keeps_the_conversations_language():
    assert lang.of("٢٢", fallback="en") == "en" and lang.of("؟", fallback="en") == "en"


# A tool's reply is ours only where a phrase made it: the web summary is the model's words,
# and an Arabic one to an English message (or the other way) is caught, not set aside as a
# name. The names a phrase was filled with (a device's label, a row's text) still are.
@pytest.mark.parametrize("language, summary", [
    ("en", "الأسعار ارتفعت مرة تانية هالأسبوع."),
    ("ar", "Prices went up again this week, according to the news."),
])
def test_a_tools_reply_in_the_wrong_language_is_caught(language, summary):
    from app.brain import language_guard as G
    from app.features import research
    with lang.using(language), lang.naming() as named:
        reply = research._with_sources(summary, ["https://example.com/a"])
        names = G.names_of("what's new?" if language == "en" else "شو الأخبار؟",
                           [("web_search", {"ok": True, "reply": reply})], named)
    assert G.wrong_language(reply, language, names) is True


@pytest.mark.parametrize("language, label", [("en", "ضو الصالة"), ("ar", "Desk lamp")])
def test_the_names_a_phrase_was_filled_with_are_still_names(language, label):
    from app.brain import language_guard as G
    with lang.using(language), lang.naming() as named:
        reply = lang.say("device_on", label=label)
        names = G.names_of("hi" if language == "en" else "هلا", [("x", {"reply": reply})], named)
    assert G.wrong_language(reply, language, names) is False


# A short reply all in the other language is caught: «Done ✅» on an Arabic turn had no word
# counted (a Capitalised one is a name beside Arabic words, not with none at all).
@pytest.mark.parametrize("text, language", [
    ("Done ✅", "ar"),
    ("Sure!", "ar"),
    ("OK, Nabeel.", "ar"),
    ("تم ✅", "en"),
    ("أكيد!", "en"),
])
def test_a_short_reply_in_the_other_language_is_caught(text, language):
    from app.brain import language_guard as G
    assert G.wrong_language(text, language) is True, text


def test_a_short_english_reply_to_an_arabic_message_is_rewritten(brain_db):  # noqa: F811
    model = ScriptedModel(text_reply("Sure!"), text_reply("أكيد!"))
    assert _turn(model, "بتحبي القهوة؟")["final_response"] == "أكيد!"


# What the review found Arabic-only on 29 Oct 2026, now in the turn's language.
@pytest.mark.parametrize("language", ["en", "ar"])
def test_the_web_summary_fallback_and_the_cut_file_note_come_in_the_language(language):
    from app.features import attachments, research
    with lang.using(language):
        empty = research._with_sources("", [])
        cut = attachments.extract_text(b"x" * (attachments.MAX_TEXT_CHARS + 5), "text/plain")
    assert lang.PHRASES["research_no_summary"][language] in empty
    assert cut.endswith(lang.PHRASES["file_cut"][language])


# The second honesty pass puts the tools' replies in once: the first pass already put them in
# the body the rewrite translated (review of 29 Oct 2026).
@pytest.mark.parametrize("message, item, first, rewrite", [
    ("add milk please", "milk", "حذفت الخبز. القائمة جاهزة.",
     "Added «milk» ✅\nDeleted the bread. The list is ready."),
    ("ضيفي حليب", "حليب", "Deleted the bread. The list is ready.",
     "ضفت «حليب» ✅\nحذفت الخبز. القائمة جاهزة."),
])
def test_the_second_honesty_pass_does_not_repeat_the_tools_replies(brain_db, message, item,  # noqa: F811
                                                                   first, rewrite):
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text=item)),
                          text_reply(first), text_reply(rewrite))
    out = _turn(model, message)["final_response"]
    assert out.count(f"«{item}»") == 1, out


# «add lemon to the list» on a call was saved as «ليمون» (29 Oct 2026): the chat's rule that a
# tool gets his own words in his own language was not in the call's instructions.
@pytest.mark.parametrize("words", ["text=«lemon»", "text=«حليب»"])
def test_the_call_gives_a_tool_his_own_words_as_the_chat_does(monkeypatch, words):
    from app.api.voice_ws import tools as voice_tools
    from app.brain import context
    monkeypatch.setattr("app.brain.context.profile_block", lambda chat_id: "")
    body = voice_tools._system_instruction_body("", False)
    assert context.TOOL_WORDS_RULE.strip() in body and "never translated" in body
    assert words in body
