"""What the model passes for a time or a row's details is read, never a dead end (traces of
29 Oct 2026): «remind me now» came as when="now" or a bad in_minutes and failed, and a task
added by voice with data.time was refused whole."""
from __future__ import annotations

from datetime import timedelta

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import items, schedules
from app.brain import lang, tools
from app.brain import when as W
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import active_user_profile_context


def _run(name, language="en", **args):
    with active_user_profile_context(A), lang.using(language):
        return tools.execute(name, args, TurnCtx(user_id="userA"))


@pytest.mark.parametrize("language, args", [
    ("en", {"when": "now"}),
    ("en", {"when": "right now"}),
    ("ar", {"when": "هلّق"}),
    ("ar", {"when": "هلأ"}),
    ("en", {"in_minutes": 0}),
    ("ar", {"in_minutes": 0}),
])
def test_a_reminder_for_now_is_set_for_now(brain_db, language, args):  # noqa: F811
    out = _run("schedule", language, kind="reminder", text="call mom", **args)
    assert out["ok"], out
    with active_user_profile_context(A):
        row = schedules.get(out["id"])
    assert W.aware_utc(row["fire_at"]) <= W.now_utc() + timedelta(minutes=2)


@pytest.mark.parametrize("language, minutes", [("en", -5), ("ar", "half an hour"), ("en", "نص ساعة")])
def test_a_time_it_cannot_read_asks_the_model_to_ask(brain_db, language, minutes):  # noqa: F811
    out = _run("schedule", language, kind="reminder", text="call mom", in_minutes=minutes)
    assert not out["ok"] and "ask the user" in out["error"], out


def test_minutes_given_as_a_number_in_text_are_read(brain_db):  # noqa: F811
    out = _run("schedule", kind="reminder", text="call mom", in_minutes="30")
    assert out["ok"], out


@pytest.mark.parametrize("language, text", [("en", "call the bank"), ("ar", "اتصل بالبنك")])
def test_a_data_field_the_kind_does_not_have_is_set_aside(brain_db, language, text):  # noqa: F811
    out = _run("list_add", language, list="tasks", text=text, data={"time": "17:00", "notes": "x"})
    assert out["ok"], out
    with active_user_profile_context(A):
        assert items.get(out["id"])["data"] == {"notes": "x"}
