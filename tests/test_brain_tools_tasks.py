"""The task tools (`brain/tools_tasks.py`): a task is shown and waits for a yes before it is
saved, may only read and tell, is run by talk («شو المهام الشغّالة؟», «وقّفيها», «خلّيها كل
ساعتين»), and is there only for an account with the `tasks` switch on. In both languages."""
from __future__ import annotations

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import schedules, tasks
from app.brain import lang, loop, tools
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import active_user_profile_context

MOSTAQL = {"title": "مشاريع مستقل", "instructions": "كل ساعة شوفي مشاريع جديدة على مستقل",
           "every_minutes": 60, "check_tool": "web_search",
           "check_args": {"query": "site:mostaql.com مشاريع"}, "notify_when": "مشروع جديد",
           "tools": ["web_search"]}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')


def _run(name, language="ar", confirmed=False, **args):
    with active_user_profile_context(A), lang.using(language):
        ctx = TurnCtx(user_id="userA")
        ctx.confirmed = confirmed
        return tools.execute(name, args, ctx)


def _turn(model, message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             complete=model)


def test_the_tools_are_there_only_with_the_switch_on(monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    names = {s["function"]["name"] for s in tools.openai_tools("userA")}
    assert {"task_create", "task_list", "task_update", "task_cancel"} <= names
    assert not {"task_create"} & {s["function"]["name"] for s in tools.openai_tools("userB")}
    assert not {"task_create"} & {d["name"] for d in tools.declarations()}


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_task_waits_for_a_yes_and_is_saved_on_it(brain_db, on, language):  # noqa: F811
    asked = _run("task_create", language, **MOSTAQL)
    assert asked.get("needs_confirmation") and "مشاريع مستقل" in asked["summary"]
    with active_user_profile_context(A):
        assert tasks.running() == []
    saved = _run("task_create", language, confirmed=True, **MOSTAQL)
    assert saved["ok"]
    with active_user_profile_context(A):
        row = tasks.running()[0]
    assert row["recurrence"] == "FREQ=MINUTELY;INTERVAL=60" and row["payload"]["lang"] == language
    assert row["payload"]["probe"] == {"tool": "web_search", "args": {"query": "site:mostaql.com مشاريع"}}


def test_the_yes_in_a_turn_saves_it(brain_db, on):  # noqa: F811
    model = ScriptedModel(tools_reply(call("task_create", **MOSTAQL)), text_reply("ok"))
    state = _turn(model, MOSTAQL["instructions"])
    assert state["pending_state"]
    with active_user_profile_context(A):
        assert tasks.running() == []
        loop.run_turn("اه", user_id="userA", chat_id="userA", source="web",
                      pending_state=state["pending_state"], complete=ScriptedModel(text_reply("تم")))
        assert len(tasks.running()) == 1


# The words are a question, not the guard (review of phase one): a task's tools only read, so
# nothing it is told can pay, send, publish or delete. Words that ask for one make the yes it
# waits for say so; a read («tell me if its price drops») is asked plainly.
_ACTS = [
    ("ar", "كل يوم ادفعي فاتورة الكهربا من حسابي"),
    ("ar", "أول كل شهر سدّدي فاتورة النت"),
    ("ar", "إذا وصل الراتب حوّلي ألف لحساب أمي"),
    ("ar", "كل يوم ابعتي إيميل باسمي للزباين"),
    ("ar", "كل أسبوع انشري صورة على إنستغرام"),
    ("ar", "كل يوم امسحي الرسايل القديمة"),
    ("en", "every day pay my electricity bill from my account"),
    ("en", "when my salary arrives, transfer 500 to savings"),
    ("en", "every morning post on Instagram what's new"),
    ("en", "every week remove the old items from my list"),
    ("en", "send an email in my name to my clients every Monday"),
]
_READS = [
    ("ar", "كل ساعة شوفي سعر الدولار وقلّيلي إذا نزل سعره"),
    ("ar", "كل ساعة شوفي مشاريع جديدة على مستقل وابعتيلي الجديد"),
    ("en", "check the gold price every hour and tell me if it drops"),
    ("en", "every hour, check Mostaql for new projects and send me the new ones"),
]


@pytest.mark.parametrize("language, words", _ACTS)
def test_words_that_ask_to_act_make_the_yes_say_a_task_only_reads(brain_db, on, language, words):  # noqa: F811
    out = _run("task_create", language, **{**MOSTAQL, "instructions": words})
    assert out.get("needs_confirmation")
    assert out["summary"] == lang.PHRASES["task_confirm_reads_only"][language].format(
        title=MOSTAQL["title"], every=lang.PHRASES["every_hours"][language].format(n=1),
        how=lang.PHRASES["delivery_hourly"][language])
    with active_user_profile_context(A):
        assert tasks.running() == []


@pytest.mark.parametrize("language, words", _READS)
def test_a_read_is_asked_plainly(brain_db, on, language, words):  # noqa: F811
    out = _run("task_create", language, **{**MOSTAQL, "instructions": words})
    assert out.get("needs_confirmation")
    assert out["summary"] == lang.PHRASES["task_confirm"][language].format(
        title=MOSTAQL["title"], every=lang.PHRASES["every_hours"][language].format(n=1),
        how=lang.PHRASES["delivery_hourly"][language])


@pytest.mark.parametrize("args", [{"check_tool": "list_delete"}, {"tools": ["device_control"]}])
def test_a_task_may_only_read_and_tell(brain_db, on, args):  # noqa: F811
    out = _run("task_create", confirmed=True, **{**MOSTAQL, **args})
    assert not out["ok"]


def test_without_the_switch_no_task_is_made(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    assert not _run("task_create", confirmed=True, **MOSTAQL)["ok"]


@pytest.mark.parametrize("language", ["ar", "en"])
def test_it_is_run_by_talk(brain_db, on, language):  # noqa: F811
    _run("task_create", language, confirmed=True, **MOSTAQL)
    listed = _run("task_list", language)
    assert listed["ok"] and listed["tasks"][0]["title"] == "مشاريع مستقل"
    tid = listed["tasks"][0]["id"]
    assert _run("task_update", language, id=tid, pause=True)["ok"]
    with active_user_profile_context(A):
        assert schedules.get(tid)["status"] == "paused"
    assert _run("task_update", language, match_text="مستقل", resume=True, every_minutes=120)["ok"]
    with active_user_profile_context(A):
        row = schedules.get(tid)
    assert row["status"] == "pending" and row["recurrence"].endswith("INTERVAL=120")
    assert _run("task_cancel", language, match_text="مستقل")["ok"]
    with active_user_profile_context(A):
        assert tasks.running() == []
    assert _run("task_list", language)["reply"] == lang.PHRASES["task_none"][language]


def test_the_tasks_rule_is_in_the_prompt_only_with_the_switch_on(brain_db, monkeypatch):  # noqa: F811
    from app.brain import context
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    with active_user_profile_context(A):
        assert context.TASKS_RULE.strip() in context.build_system("userA", "hi")
        assert context.TASKS_RULE.strip() not in context.build_system("userB", "hi")


@pytest.mark.parametrize("language, words", [
    ("ar", "تابعي مواعيد تسليم مشاريعي، وذكّريني قبل يومين"),
    ("en", "Track my project deadlines and remind me two days before"),
])
@pytest.mark.parametrize("extra", ["schedule", "device_control"])
def test_a_task_is_never_given_a_tool_that_writes_or_switches(brain_db, on, language, words, extra):  # noqa: F811
    args = {**MOSTAQL, "instructions": words, "check_tool": "recall", "tools": ["recall", extra]}
    out = _run("task_create", language, confirmed=True, **args)
    assert not out["ok"]
    assert "schedule" not in tools_tasks_schema_enum()


def tools_tasks_schema_enum():
    from app.brain import tools_tasks
    create = next(s for s in tools_tasks.TASK_SCHEMAS if s["name"] == "task_create")
    return create["parameters"]["properties"]["tools"]["items"]["enum"]
