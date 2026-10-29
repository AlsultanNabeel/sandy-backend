"""The task tools in a call, behind the `tasks` switch: offered to the live model with their
check's fields spelled out (Gemini refuses a free-form object), the rule that makes one at once
on a guess, and the same yes before anything is saved; in both languages."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import tasks
from app.brain import lang, voice
from app.brain.context import TASKS_RULE
from app.utils.user_profiles import active_user_profile_context

TASK_TOOLS = {"task_create", "task_list", "task_update", "task_cancel"}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')


def _names(decls):
    return {d["name"] for d in decls}


def test_the_call_offers_the_task_tools_only_with_the_switch(on):
    assert TASK_TOOLS <= _names(voice.declarations(user_id="userA"))
    assert not TASK_TOOLS & _names(voice.declarations(user_id="userB"))
    assert not TASK_TOOLS & _names(voice.declarations())


def test_the_checks_arguments_are_fields_the_live_model_can_fill(on):
    [create] = [d for d in voice.declarations(user_id="userA") if d["name"] == "task_create"]
    check = create["parameters"]["properties"]["check_args"]
    assert check["type"] == "object" and {"query", "period"} <= set(check["properties"])

    def free_form(schema):
        return schema.get("type") == "object" and not schema.get("properties")
    assert not any(free_form(v) for v in check["properties"].values())


def test_the_session_builds_its_tools_for_the_caller(on):
    from app.api.voice_ws.tools import _build_live_tools
    types = NS(Tool=lambda function_declarations: function_declarations)
    assert TASK_TOOLS <= _names(_build_live_tools(types, user_id="userA")[0])
    assert not TASK_TOOLS & _names(_build_live_tools(types, user_id="userB")[0])


def test_the_calls_context_carries_the_tasks_rule_only_with_the_switch(on, brain_db):  # noqa: F811
    from app.api.voice_ws.memory import session_context_for
    assert TASKS_RULE.strip() in session_context_for("userA", "التطبيق", "", history=[])
    assert TASKS_RULE.strip() not in session_context_for("userB", "التطبيق", "", history=[])


@pytest.mark.parametrize("language,yes", [("ar", "اه"), ("en", "yes")])
def test_a_task_is_shown_and_saved_only_after_his_yes(on, brain_db, language, yes):  # noqa: F811
    args = {"title": "Gold" if language == "en" else "الدهب",
            "instructions": "check the gold price" if language == "en" else "شوفي سعر الدهب",
            "every_minutes": 60, "check_tool": "web_search",
            "check_args": {"query": "gold price"}, "notify_when": "it moves"}
    with active_user_profile_context(A), lang.using(language):
        held = voice.dispatch("task_create", args, "userA")
        assert held["handled"] and tasks.running() == []
        done = voice.dispatch("confirm", {"answer": yes}, "userA")
        [row] = tasks.running()
    assert done.get("ok") is not False
    assert row["payload"]["probe"] == {"tool": "web_search", "args": {"query": "gold price"}}
    assert row["payload"]["lang"] == language


def test_a_task_that_asks_to_pay_is_refused_in_a_call_too(on, brain_db):  # noqa: F811
    with active_user_profile_context(A), lang.using("ar"):
        out = voice.dispatch("task_create", {"title": "دفع", "instructions": "ادفعي الفاتورة كل شهر",
                                             "every_minutes": 1440, "check_tool": "recall"}, "userA")
        assert tasks.running() == [] and out.get("ok") is False
