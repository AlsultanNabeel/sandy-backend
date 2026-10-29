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


def test_no_tool_reply_is_written_in_one_language_only():
    """A reply the user reads is a phrase in both languages (`lang.PHRASES`), never a
    literal in the tool's code."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "cloud" / "app" / "brain"
    arabic_reply = re.compile(r"""(?:"reply":\s*|reply=)f?["'][^"'\n]*[؀-ۿ]""")
    for name in ("tools_blocks.py", "tools_world.py", "confirm.py", "honesty.py", "loop.py"):
        found = arabic_reply.findall((root / name).read_text(encoding="utf-8"))
        assert not found, f"{name}: {found}"


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
    assert "English" in model.seen[1][0]["content"] and model.seen[1][-1]["content"] == "تمام، رح أذكّرك بكرا ⏰"


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
