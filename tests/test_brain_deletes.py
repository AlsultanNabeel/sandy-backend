"""Deletes and edits: one row or a few named ones run at once, on chat and voice alike;
only a bulk change (more than five rows at once) asks, once."""
from __future__ import annotations

from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import items
from app.brain import loop, voice
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message, pending=None):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model)


def _add(*texts, list_name="shopping"):
    with active_user_profile_context(A):
        return [items.add(list_name, t) for t in texts]


def _left(ids):
    with active_user_profile_context(A):
        return [i for i in ids if items.get(i) is not None]


def test_one_delete_by_id_runs_at_once(brain_db):  # noqa: F811
    milk, = _add("حليب")
    model = ScriptedModel(tools_reply(call("list_delete", id=milk)),
                          text_reply("شلت الحليب ✅"))
    state = _turn(model, "شيلي الحليب من القائمة")
    assert _left([milk]) == []
    assert state["pending_state"] is None
    assert "متأكد" not in state["final_response"]


def test_a_few_named_deletes_in_one_line_run_at_once(brain_db):  # noqa: F811
    ids = _add("حليب", "خبز", "بيض")
    model = ScriptedModel(tools_reply(*[call("list_delete", cid=f"c{n}", id=i)
                                        for n, i in enumerate(ids)]), text_reply("شلتهم"))
    state = _turn(model, "شيلي الحليب والخبز والبيض")
    assert _left(ids) == [] and state["pending_state"] is None


def test_more_than_five_rows_at_once_asks_once(brain_db):  # noqa: F811
    ids = _add(*[f"جيم {n}" for n in range(6)], list_name="tasks")
    model = ScriptedModel(tools_reply(call("list_delete", list="tasks", match_text="جيم",
                                           all_matching=True)), text_reply(""))
    state = _turn(model, "احذفي كل مهام الجيم")
    assert state["final_response"].startswith("متأكد إنك بدك تحذف")
    assert len(_left(ids)) == 6
    _turn(ScriptedModel(), "اه", pending=state["pending_state"])
    assert _left(ids) == []


def test_five_matching_rows_run_at_once(brain_db):  # noqa: F811
    ids = _add(*[f"جيم {n}" for n in range(5)], list_name="tasks")
    model = ScriptedModel(tools_reply(call("list_delete", list="tasks", match_text="جيم",
                                           all_matching=True)), text_reply("حذفتهم"))
    state = _turn(model, "احذفي مهام الجيم")
    assert _left(ids) == [] and state["pending_state"] is None


def test_one_cancel_runs_at_once(brain_db):  # noqa: F811
    from datetime import datetime, timedelta, timezone

    from app.blocks import schedules

    with active_user_profile_context(A):
        sid = schedules.add("reminder", "الدوا", datetime.now(timezone.utc) + timedelta(hours=2))
    model = ScriptedModel(tools_reply(call("schedule_cancel", id=sid)),
                          text_reply("لغيته"))
    state = _turn(model, "الغي تذكير الدوا")
    with active_user_profile_context(A):
        assert schedules.get(sid)["status"] == "cancelled"
    assert state["pending_state"] is None


def test_voice_one_delete_runs_at_once(brain_db):  # noqa: F811
    milk, = _add("حليب")
    with active_user_profile_context(A):
        out = voice.dispatch("list_delete", {"id": milk}, "userA")
    assert out["ok"] and _left([milk]) == []


# ── what is not there is said to be not there ────────────────────────────────

def _run(name, **args):
    from app.brain import tools
    from app.brain.ctx import TurnCtx

    with active_user_profile_context(A):
        return tools.execute(name, args, TurnCtx(user_id="userA"))


def test_a_row_that_is_not_there_is_said_to_be_not_there(brain_db):  # noqa: F811
    _add("خبز")
    out = _run("list_delete", list="shopping", match_text="حليب")
    assert out["ok"] is False and "ما لقيت «حليب»" in out["reply"]
    out = _run("list_delete", id="0" * 32)
    assert out["ok"] is False and "ما لقيت" in out["reply"]
    out = _run("log_delete", kind="expense")
    assert out["ok"] is False and "ما لقيت" in out["reply"]
    out = _run("schedule_cancel", match_text="الدكتور")
    assert out["ok"] is False and "ما لقيت «الدكتور»" in out["reply"]


def test_a_near_spelling_is_not_acted_on_and_the_closest_is_named(brain_db):  # noqa: F811
    net, = _add("دفع فاتورة النت", list_name="tasks")
    out = _run("list_delete", match_text="دفع فاتورة المي")
    assert out["ok"] is False and "needs_confirmation" not in out
    assert "ما لقيت «دفع فاتورة المي»" in out["reply"] and "«دفع فاتورة النت»" in out["reply"]
    assert _left([net]) == [net]


def test_voice_says_what_is_not_there(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        out = voice.dispatch("list_delete", {"match_text": "حليب"}, "userA")
    assert out["reply"].startswith("[لم يُنفَّذ] ما لقيت «حليب»")


# ── deleting is a tool of its own, never a flag on an edit ───────────────────

def test_deleting_is_its_own_tool_per_block_and_no_edit_takes_a_delete_flag():
    from app.brain import tools

    by_name = {d["name"]: d["parameters"]["properties"] for d in tools.declarations()}
    assert {"list_delete", "log_delete", "schedule_cancel"} <= set(by_name)
    assert "delete" not in by_name["list_update"] and "delete" not in by_name["log_update"]
    assert "cancel" not in by_name["schedule_update"]


def test_delete_the_last_expense(brain_db):  # noqa: F811
    from datetime import datetime, timedelta, timezone

    from app.blocks import entries

    now = datetime.now(timezone.utc)
    with active_user_profile_context(A):
        older = entries.add("expense", "قهوة", {"amount": 5}, at=now - timedelta(hours=1))
        newest = entries.add("expense", "غدا", {"amount": 40}, at=now)
    model = ScriptedModel(tools_reply(call("log_delete", kind="expense")), text_reply("حذفت الغدا"))
    state = _turn(model, "احذفي آخر مصروف")
    with active_user_profile_context(A):
        assert entries.get(newest) is None and entries.get(older) is not None
    assert state["pending_state"] is None


def test_emptying_a_list_asks_once_however_short_it_is(brain_db):  # noqa: F811
    ids = _add("حليب", "خبز")
    model = ScriptedModel(tools_reply(call("list_delete", list="shopping", everything=True)),
                          text_reply(""))
    state = _turn(model, "فضّي قائمة التسوق")
    assert state["final_response"].startswith("متأكد إنك بدك تحذف") and len(_left(ids)) == 2
    _turn(ScriptedModel(), "اه", pending=state["pending_state"])
    assert _left(ids) == []


def test_a_few_rows_by_id_in_one_call(brain_db):  # noqa: F811
    ids = _add("حليب", "خبز", "بيض")
    out = _run("list_delete", ids=ids[:2] + ["0" * 32])
    assert out["ok"] and _left(ids) == ids[2:] and "ما لقيتهم" in out["reply"]


# ── an edit that changes nothing says so ─────────────────────────────────────

def test_an_edit_that_changes_nothing_is_not_a_success(brain_db):  # noqa: F811
    from datetime import datetime, timedelta, timezone

    from app.blocks import entries, schedules

    milk, = _add("حليب")
    with active_user_profile_context(A):
        eid = entries.add("expense", "غدا", {"amount": 40})
        sid = schedules.add("reminder", "الدوا", datetime.now(timezone.utc) + timedelta(hours=2))
    for name, args in [("log_update", {"kind": "expense"}),           # the 19 Oct «deleted»
                       ("log_update", {"id": eid, "amount": 40}),
                       ("list_update", {"id": milk}),
                       ("list_update", {"id": milk, "text": "حليب"}),
                       ("schedule_update", {"id": sid})]:
        out = _run(name, **args)
        assert out["ok"] is False and out["reply"].startswith("ما تغيّر شي"), (name, args, out)
    assert _run("log_update", id=eid, amount=45)["ok"]
    assert _run("list_update", id=milk, text="حليب لوز")["ok"]
