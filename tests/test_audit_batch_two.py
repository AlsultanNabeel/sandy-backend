"""Regressions for batch two of the 24 Aug 2026 audit: `handled` meant two things.

`handled` answered *"did a handler produce a reply"*. Readers that wanted a
different question — *"did the thing happen"* — got yes for every refusal. A
task whose write failed was confirmed as saved, the graph put a ✅ on
`سجّل دخولك`, and the voice path handed Gemini a refusal as ordinary text.

A third question came out of it: *"is the tool broken"*. That is what
`tool_health` asks, and it is not `ok` either. `_history` is process-global and
keyed by tool name alone, so scoring refusals as failures makes three different
customers mistyping a shopping item enough to tell the owner his shopping tool
is broken — while the one thing the monitor exists to catch, a tool that
actually raises, went on being recorded as a clean call.

Tests go through the production call path rather than the function in
isolation, because reachability is the point: the ✅ append and the degradation
warning both sat in a `response_node` branch that needs a node setting
`execution_result` *without* `final_response`, and every node sets both.

**Four tests here pass against the pre-fix code too, deliberately.** They do
not describe a defect; they pin the blast radius of the ones that do. Widening
"a refusal is not a success" into "a refusal is a failure", or into "everything
is a failure", is the obvious way to get this change wrong, and each of those
four is one edge of that.
"""
from __future__ import annotations

import mongomock
import pytest


GUEST = {"user_id": "guest-1", "chat_id": "guest-1", "name": "Guest",
         "is_owner": False, "is_guest": True, "permissions": "limited",
         "relation": "guest"}

OWNER = {"user_id": "guest-1", "chat_id": "guest-1", "name": "Owner",
         "is_owner": True, "is_guest": False, "permissions": "all",
         "relation": "owner"}


@pytest.fixture()
def db():
    import app.db as appdb
    from app.agent import tool_health
    from app.agent.tools.setup import register_all_tools

    database = mongomock.MongoClient()["t"]
    appdb.configure(database)
    register_all_tools()
    # `tool_health._history` is a module-level dict shared by the whole process.
    # A test that leaves a tool at 0% poisons whatever runs next.
    tool_health.reset()
    try:
        yield database
    finally:
        tool_health.reset()
        appdb.reset()


def _ctx(db, message="اختبار"):
    from app.agent.tools.dispatcher import DispatchContext

    return DispatchContext(
        user_message=message,
        normalized_message=message,
        session={"_destructive_confirmed": True},
        state={"chat_id": "guest-1", "user_id": "guest-1", "message": message},
        mongo_db=db,
        create_chat_completion_fn=None,
    )


# ── The contract itself ──────────────────────────────────────────────────────

def test_a_result_without_ok_reads_as_its_handled_value():
    """The default is what makes the migration safe.

    ~330 sites return `handled` and say nothing about `ok`. If the fallback
    were `False`, every one of them would have started reporting failure the
    moment this landed.
    """
    from app.agent.tool_result import result_ok

    assert result_ok({"handled": True}) is True
    assert result_ok({"handled": False}) is False
    assert result_ok({"handled": True, "ok": False}) is False
    assert result_ok({"handled": False, "ok": True}) is True
    assert result_ok(None) is False


# ── 1. A refusal is not a confirmation ───────────────────────────────────────

def test_a_failed_write_is_not_reported_as_a_saved_task(db, monkeypatch):
    """`سجّلتها ✅ 3 مهام` with zero rows written — **the reachable half.**

    `tasks_store.add_task` swallows every exception and returns `""`: Mongo
    down, a duplicate key, a due date in the past. `_handle_create` turns that
    into `ما قدرت أضيف المهمة.` with `handled=True`, and the adapter above
    overwrote it with the prepared success sentence.

    This, not the guest case, is what a user actually hits: `execute_node`
    blocks `task_*` for guests before dispatch, so the executor's own guest
    refusal is unreachable from the graph.
    """
    import app.agent.executor.task_handlers.creation as creation
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    monkeypatch.setattr(creation, "add_task", lambda *a, **kw: "")

    with user_profiles.active_user_profile_context(OWNER):
        single = ToolDispatcher().dispatch(
            "task_create", {"title": "حليب"}, _ctx(db))
        multi = ToolDispatcher().dispatch(
            "task_create", {"titles": ["أ", "ب", "ج"]}, _ctx(db))

    assert db["sandy_tasks"].count_documents({}) == 0
    for result in (single, multi):
        assert "سجّلتها" not in str(result.get("reply", "")), \
            "a write that failed was reported as a saved task"
        assert result.get("ok") is False


def test_a_partial_failure_names_what_was_lost(db, monkeypatch):
    """Ask for three, two write, one does not.

    The old code counted the failed one as created. Merely not counting it is
    still wrong: the user is told about two and never learns the third is gone.
    """
    import app.agent.executor.task_handlers.creation as creation
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        return "" if calls["n"] == 2 else f"id-{calls['n']}"

    monkeypatch.setattr(creation, "add_task", _flaky)
    with user_profiles.active_user_profile_context(OWNER):
        result = ToolDispatcher().dispatch(
            "task_create", {"titles": ["أ", "ب", "ج"]}, _ctx(db))

    reply = str(result.get("reply", ""))
    assert "'أ'" in reply and "'ج'" in reply
    assert "'ب'" in reply.split("بس ما قدرت")[-1], \
        f"the failed title is not named: {reply!r}"
    assert result.get("ok") is False


def test_a_guest_refusal_is_not_a_success(db):
    """The executor's own guest gate, one layer below the graph's.

    Unreachable through `execute_node` today, and kept because the gate is
    transitional: the tool is what enforces this if the node's prefix list ever
    stops matching a tool name.
    """
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(GUEST):
        result = ToolDispatcher().dispatch(
            "task_create", {"titles": ["أ", "ب", "ج"]}, _ctx(db))

    assert db["sandy_tasks"].count_documents({}) == 0
    # The reason survives instead of being flattened to "تم."
    assert "سجّل دخولك" in str(result.get("reply", ""))
    assert result.get("ok") is False


# ── 2. The health monitor scores breakage, not refusals ──────────────────────

def test_a_tool_that_raises_is_not_recorded_as_healthy(db, monkeypatch):
    """The one failure the monitor exists to catch, and the one it missed.

    `executor/dispatch.py::_guard` catches the exception and returns
    `handled=True` with a friendly sentence — which read as a clean call all
    the way to `tool_health`. The weather API could raise on every single
    request and `get_capabilities` still answered `كل قدراتي شغالة تمام`.
    """
    import app.features.weather as weather_mod
    from app.agent import tool_health
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    def _boom(*a, **kw):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(weather_mod, "get_weather", _boom)
    with user_profiles.active_user_profile_context(OWNER):
        for _ in range(4):
            ToolDispatcher().dispatch("get_weather", {"city": "عمّان"}, _ctx(db))

    snap = tool_health.get_health("get_weather")
    assert snap["n_calls"] == 4
    assert snap["success_rate"] == 0.0
    assert snap["status"] == "degraded"


def test_ordinary_refusals_do_not_mark_a_working_tool_broken(db):
    """**The trap in making health honest**, and why it reads `error` not `ok`.

    `_history` is keyed by tool name alone and shared by the whole process — it
    is not per tenant. At `_DEGRADED_MIN_CALLS = 3`, scoring refusals as
    failures means three *different* customers each mistyping a shopping item
    once is enough for the owner to be told his shopping tool is broken.
    """
    from app.agent import tool_health
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(OWNER):
        for _ in range(5):
            out = ToolDispatcher().dispatch(
                "shopping_check", {"item": "مش موجود"}, _ctx(db))

    assert "ما لقيت" in str(out.get("reply", "")), "this must still be a refusal"
    snap = tool_health.get_health("shopping_check")
    assert snap["success_rate"] == 1.0
    assert snap["status"] != "degraded"


# ── 3. The graph does not tick a refusal ─────────────────────────────────────

def test_the_graph_does_not_put_a_tick_on_a_guest_refusal(db):
    """`سجّل دخولك عشان أقدر أساعدك بهالطلب 😊 ✅`.

    Runs execute_node → response_node, not `response_node` alone: the append
    lived in the `elif reply:` branch, and `execute_node`'s guest refusal —
    which sets `execution_result` and no `final_response` — was the only live
    way in. Every handler that wants a tick writes its own (`سجّلتها ✅`), so
    the generic append reached nothing but this, and it is gone.
    """
    from app.agent.nodes.execute import execute_node
    from app.agent.nodes.response import response_node
    from app.utils import user_profiles

    state = {
        "chat_id": "guest-1", "user_id": "guest-1", "message": "احذف مهمة",
        "function_call": {"name": "task_delete", "args": {"reference": "1"}},
    }
    with user_profiles.active_user_profile_context(GUEST):
        after_exec = execute_node(dict(state))
        text = response_node(after_exec)["final_response"]

    assert not after_exec.get("final_response"), \
        "execute_node started setting final_response — this test no longer " \
        "covers the branch it was written for"
    assert "سجّل دخولك" in text
    assert "✅" not in text


def test_the_degradation_warning_reaches_a_user_at_all(db):
    """**It never has.**

    `_degradation_disclosure` sat in `response_node`'s `elif reply:` branch,
    which needs a node that sets `execution_result` and leaves `final_response`
    unset. Every node sets both. So the only user-facing surface `tool_health`
    has was dead from the day it was written, which is the real reason nobody
    ever saw a warning — the recording bug above merely guaranteed it twice.
    """
    from app.agent import tool_health
    from app.agent.nodes.response import response_node

    for _ in range(5):
        tool_health.record_call("get_weather", ok=False, latency_ms=1.0,
                                error="upstream down")
    assert tool_health.get_health("get_weather")["status"] == "degraded"

    text = response_node({
        # A node that set final_response — i.e. every single one of them.
        "final_response": "الطقس اليوم مشمس.",
        "execution_result": {"handled": True, "reply": "الطقس اليوم مشمس."},
        "function_call": {"name": "get_weather"},
    })["final_response"]

    assert "⚠️" in text
    assert "الطقس اليوم مشمس." in text


def test_a_degraded_tool_does_not_apologise_on_top_of_a_refusal(db):
    """The disclosure says "جرّبت أعمل اللي طلبته، بس لو بان ناقص خبّرني" —
    a sentence about work that happened. On a refusal it is a lie."""
    from app.agent import tool_health
    from app.agent.nodes.response import response_node

    for _ in range(5):
        tool_health.record_call("get_weather", ok=False, latency_ms=1.0,
                                error="upstream down")

    text = response_node({
        "final_response": "ما قدرت أجيب بيانات الطقس لـ عمّان حالياً.",
        "execution_result": {
            "handled": True, "ok": False,
            "reply": "ما قدرت أجيب بيانات الطقس لـ عمّان حالياً."},
        "function_call": {"name": "get_weather"},
    })["final_response"]

    assert "⚠️" not in text


# ── 4. The voice path tells the model the truth ──────────────────────────────

def test_voice_labels_breakage_and_relays_a_refusal_in_its_own_words(db, monkeypatch):
    """Gemini reads the tool response as text, and both mistakes are live.

    Hand her an *unmarked* refusal and she assumes it worked and confirms it —
    that is half the "she says she did it" report, and
    `tests/test_voice_tools_actually_run.py` already pins it. Hand her
    `[فشل التنفيذ]` on top of "ما لقيت جهاز بهالاسم، أي واحد تقصد؟" and she
    abandons a disambiguation the user is halfway through. So everything that
    did not happen is marked, and the two are marked differently.
    """
    import app.api.voice_ws.tools as vt

    class _Fixed:
        def __init__(self, result):
            self._result = result

        def dispatch(self, name, args, ctx):
            return dict(self._result)

    monkeypatch.setattr(vt, "_stm_chat_id", lambda: "owner-1")

    asking = vt._dispatch_tool(_Fixed({
        "handled": True, "ok": False,
        "reply": "ما لقيت جهاز بهالاسم. أجهزتك: نور، مروحة. أي واحد تقصد؟",
    }), "device_control", {"device": "x"}, "owner-1")
    assert asking["reply"].startswith("[لم يُنفَّذ]"), \
        "an unmarked refusal is what she reads as success and confirms"
    assert "فشل" not in asking["reply"], \
        "calling a disambiguation a failure makes her abandon it"
    assert "أي واحد تقصد؟" in asking["reply"]

    broken = vt._dispatch_tool(_Fixed({
        "handled": True, "ok": False, "error": "device_control: OSError",
        "reply": "ما قدرت أوصل للجهاز.",
    }), "device_control", {"device": "x"}, "owner-1")
    assert broken["reply"].startswith("[فشل التنفيذ]")
    # The reason travels with it — a bare "الأداة ما اشتغلت" makes her invent one.
    assert "ما قدرت أوصل للجهاز" in broken["reply"]

    # A refusal with nothing to say still has to say something.
    silent = vt._dispatch_tool(_Fixed({"handled": True, "ok": False, "reply": ""}),
                               "device_control", {"device": "x"}, "owner-1")
    assert silent["reply"].strip() not in ("[لم يُنفَّذ]", "")
    # A tool that was never found is breakage, not a refusal.
    missing = vt._dispatch_tool(_Fixed({"handled": False, "reply": "ما لقيت هالجهاز."}),
                                "device_control", {"device": "x"}, "owner-1")
    assert missing["reply"].startswith("[فشل التنفيذ]")


def test_voice_does_not_report_a_re_ask_as_a_failure(db, monkeypatch):
    """**The trap on the other side of the same line.**

    `_resolve_pending` now prefixes the handler's real
    words. That is right for a refusal and wrong for a re-ask: when the pending
    survives — "ما فهمت الوقت، اكتبه أوضح" — the flow is still alive, and
    telling Gemini it failed makes her abandon a reminder the user is halfway
    through setting. Those branches keep the default on purpose; this pins it.
    """
    import app.api.voice_ws.tools as vt
    import app.agent.executor.deps as deps

    from app.agent.pending import create_pending_action

    # Through create_pending_action so it carries the expiry the validator
    # requires — a hand-built dict is silently dropped as stale.
    pending = create_pending_action({"type": "reminder",
                                     "action": "await_remind_at",
                                     "reminder_text": "أشرب دوا"})
    monkeypatch.setattr(vt, "_stm_chat_id", lambda: "owner-1")
    monkeypatch.setattr("app.agent.pending_store.load_pending_state",
                        lambda *a, **kw: pending)
    monkeypatch.setattr("app.agent.pending_store.save_pending_state",
                        lambda *a, **kw: None)
    # The model could not read a time out of the reply — the live re-ask branch.
    monkeypatch.setattr(deps, "parse_reminder_time_ai", lambda *a, **kw: {})

    out = vt._resolve_pending("pending_confirm", "owner-1")

    assert "[فشل التنفيذ]" not in str(out.get("reply", "")), \
        "a re-ask is the handler still working, not a failed execution"
    assert "ما فهمت الوقت" in str(out.get("reply", ""))


def test_voice_still_passes_a_success_through_untouched(db, monkeypatch):
    """The guard above must not turn ordinary work into a reported failure.

    **This is the one test in the file that passed before the fix too**, and
    deliberately so: it does not describe a defect, it pins the blast radius of
    the one that does. Widening "a refusal is a failure" into "everything is a
    failure" is the obvious way to get this change wrong.
    """
    import app.api.voice_ws.tools as vt

    class _Working:
        def dispatch(self, name, args, ctx):
            return {"handled": True, "reply": "سجّلتها ✅"}

    monkeypatch.setattr(vt, "_stm_chat_id", lambda: "owner-1")
    out = vt._dispatch_tool(_Working(), "task_create", {"title": "x"}, "owner-1")

    assert "[فشل التنفيذ]" not in out["reply"]
    assert out["reply"] == "سجّلتها ✅"


# ── 5. What the fix itself nearly broke ──────────────────────────────────────
#
# Each of these is a defect the change *introduced* and a review caught. They
# are here because "a refusal is not a success" is one step away from "anything
# that is not a plain success is a failure", and that step is worse than the
# original bug.

def test_an_empty_title_is_not_a_saved_task(db):
    """The headline bug, reopened by the fallback that makes the batch safe.

    `_handle_create` asks `شو المهمة اللي بدك أضيفها؟` — an ask, so it was left
    unmarked — and `result_ok` fell back to `handled=True`. The adapter then
    wrote `سجّلتها ✅ ''` over the question. An ask that stores no pending is
    finished, and is marked.
    """
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(OWNER):
        one = ToolDispatcher().dispatch("task_create", {"title": ""}, _ctx(db))
        none = ToolDispatcher().dispatch("task_create", {"titles": []}, _ctx(db))
        blank = ToolDispatcher().dispatch(
            "task_create", {"titles": ["أ", "", "ج"]}, _ctx(db))

    for result in (one, none):
        assert "سجّلتها" not in str(result.get("reply", ""))
        assert result.get("ok") is False
    # A blank in the middle is dropped, not counted.
    assert "3 مهام" not in str(blank.get("reply", ""))
    assert db["sandy_tasks"].count_documents({}) == 2


def test_a_routing_signal_does_not_mark_a_tool_degraded(db):
    """`handled: False` is not breakage.

    `task_update` returns it for `حدّد ما تريد تعديله` — a routing signal, the
    same distinction commit `ea628a6` made on the voice path. Scoring it as a
    failure marked the tool degraded after three ordinary clarifications, and
    the newly-wired ⚠️ then prefixed every reply until the window flushed.
    """
    from app.agent import tool_health
    from app.agent.nodes.response import response_node
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(OWNER):
        for _ in range(4):
            ToolDispatcher().dispatch("task_update", {"reference": "أ"}, _ctx(db))

    assert tool_health.get_health("task_update")["status"] != "degraded"
    text = response_node({
        "final_response": "تمام، عدّلت اسم المهمة.",
        "execution_result": {"handled": True, "reply": "تمام، عدّلت اسم المهمة."},
        "function_call": {"name": "task_update"},
    })["final_response"]
    assert "⚠️" not in text


def test_the_conflict_warning_survives_the_persona_sentence(db, monkeypatch):
    """An adapter that replaces a reply must not destroy what only the handler
    knows. `task_create` swaps in a persona-toned sentence, and that used to
    take the scheduling-conflict warning with it — the one part of that reply
    carrying information rather than tone."""
    from datetime import datetime, timedelta

    import app.agent.executor.task_handlers.creation as creation
    from app.agent.tools.dispatcher import ToolDispatcher
    from app.utils import user_profiles

    future = (datetime.now().astimezone() + timedelta(days=1)).isoformat()
    # The adapter only sends `due_text`, so the due goes through the LLM parser.
    monkeypatch.setattr(creation, "parse_reminder_time_ai",
                        lambda *a, **kw: {"success": True, "remind_at_iso": future})
    monkeypatch.setattr(creation, "run_conflict_check_after_task_add",
                        lambda *a, **kw: {"alert_text": "عندك موعد ثاني بنفس الوقت"})

    with user_profiles.active_user_profile_context(OWNER):
        result = ToolDispatcher().dispatch(
            "task_create", {"title": "اجتماع", "due": future}, _ctx(db))

    assert "سجّلتها" in str(result.get("reply", "")), "the persona sentence is gone"
    assert "عندك موعد ثاني بنفس الوقت" in str(result.get("reply", ""))


def test_pending_node_carries_ok_like_execute_node(db, monkeypatch):
    """Two nodes write `execution_result`; only one was wired.

    Every `ok=False` under `executor/pending/**` was dropped on the graph path,
    so `execution_result["ok"]` meant different things depending on which node
    produced it — worse than not having it. Driven through the node rather than
    read out of the source, because the point is what reaches the next node.
    """
    import app.agent.nodes.pending as pending_node_mod
    from app.agent.pending import create_pending_action

    monkeypatch.setattr(
        pending_node_mod, "execute_pending_action",
        lambda **kw: {"handled": True, "ok": False, "reply": "ما قدرت أحذف المهمة."})

    out = pending_node_mod.pending_node({
        "chat_id": "guest-1", "user_id": "guest-1", "message": "اه",
        "intent": "pending.confirm",
        "pending_state": create_pending_action(
            {"type": "task", "action": "delete", "task_text": "أ"}),
    })

    assert out["execution_result"]["ok"] is False, \
        "a refusal resolved by pending_node reads as a success downstream"
