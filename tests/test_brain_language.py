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
