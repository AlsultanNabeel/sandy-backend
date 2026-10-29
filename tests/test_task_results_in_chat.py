"""«صباح الخير»: what a task found and he has not seen is in the chat's context when he speaks,
told once and then seen; never in a call, never without the switch, never another user's."""
from __future__ import annotations

import pytest
from brain_fakes import A, B, ScriptedModel, brain_db, text_reply  # noqa: F401

from app import notify
from app.brain import loop
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def results(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA", "userB"]}')
    monkeypatch.setattr(notify, "CHANNELS", [])
    with active_user_profile_context(A):
        notify.deliver("t1", "Mostaql", "Two new projects: P7, P9", "en")
    with active_user_profile_context(B):
        notify.deliver("t2", "Stock", "Milk is running low", "en")


def _turn(model, message, profile=A, source="web"):
    with active_user_profile_context(profile):
        return loop.run_turn(message, user_id=profile["chat_id"], chat_id=profile["chat_id"],
                             source=source, complete=model)


def _system(model):
    return model.seen[0][0]["content"]


def _unseen(profile=A):
    with active_user_profile_context(profile):
        return notify.unseen()


@pytest.mark.parametrize("message", ["صباح الخير", "good morning"])
def test_what_he_has_not_seen_is_told_once_when_he_speaks(results, message):
    model = ScriptedModel(text_reply("ok"))
    _turn(model, message)
    assert "Two new projects: P7, P9" in _system(model)
    assert "Milk is running low" not in _system(model)       # another user's
    assert _unseen() == []
    again = ScriptedModel(text_reply("ok"))
    _turn(again, message)
    assert "P7, P9" not in _system(again)
    assert len(_unseen(B)) == 1


def test_without_the_switch_it_is_not_told_and_stays_unseen(results, monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    model = ScriptedModel(text_reply("ok"))
    _turn(model, "صباح الخير")
    assert "P7, P9" not in _system(model) and len(_unseen()) == 1


def test_a_call_never_carries_it(results):
    model = ScriptedModel(text_reply("ok"))
    _turn(model, "صباح الخير", source="voice")
    assert "P7, P9" not in _system(model) and len(_unseen()) == 1


def test_a_reply_that_failed_leaves_it_for_the_next(results):
    def broken(messages, tools, on_text=None):
        raise RuntimeError("model down")
    _turn(broken, "good morning")
    assert len(_unseen()) == 1
