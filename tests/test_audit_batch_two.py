"""Regressions from the audit plan, batch two: confirmation, rewind and undo in the brain.

Each test failed before its fix and names what the user saw.
"""
from __future__ import annotations

from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import items
from app.brain import loop
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message, pending=None, **kw):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model, **kw)


def _open(lst="tasks"):
    with active_user_profile_context(A):
        return [i["text"] for i in items.list_items(lst)]


# ── W1. A yes to one delete is not a yes to the next request ─────────────────

def test_a_yes_with_a_new_delete_after_it_asks_again(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        gym = items.add("tasks", "روح عالجيم")
        report = items.add("tasks", "تقرير الشغل")
    held = _turn(ScriptedModel(tools_reply(call("list_update", id=gym, delete=True))),
                 "احذفي مهمة الجيم")["pending_state"]
    model = ScriptedModel(tools_reply(call("list_update", id=report, delete=True)))
    state = _turn(model, "اه واحذفي كمان مهمة التقرير", pending=held)
    assert "روح عالجيم" not in _open(), "the held delete itself runs"
    assert "تقرير الشغل" in _open(), "the delete in the same line ran with no question"
    assert "متأكد إنك بدك تحذف «تقرير الشغل»" in state["final_response"]
    assert state["pending_state"] is not None


# ── W2. A written-out time in the past is refused, never read as a clock ─────

def test_an_iso_time_in_the_past_or_too_far_is_refused(brain_db):  # noqa: F811
    from datetime import datetime, timedelta

    from app.brain import when

    now = datetime.now().replace(microsecond=0)
    with active_user_profile_context(A):
        assert when.parse_when((now - timedelta(hours=1)).isoformat()) is None, \
            "a reminder an hour ago was saved for ten at night"
        assert when.parse_when((now + timedelta(days=500)).isoformat()) is None
        assert when.parse_when((now + timedelta(hours=2)).isoformat()) is not None
        assert when.parse_when("بكرا الساعة 5") is not None, "words still go to the clock"


# ── W3. «Which one?» is answered by the opening of the reply, not any number in it ──

def _two_milks():
    with active_user_profile_context(A):
        a = items.add("shopping", "حليب بقر")
        b = items.add("shopping", "حليب لوز")
    held = _turn(ScriptedModel(tools_reply(call("list_update", list="shopping",
                                                match_text="حليب", done=True))),
                 "شطبي الحليب")["pending_state"]
    assert held and held["action"] == "choose"
    return a, b, held


def _done(iid):
    with active_user_profile_context(A):
        return items.get(iid)["done"]


def test_a_number_further_on_is_a_new_request_not_a_pick(brain_db):  # noqa: F811
    a, b, held = _two_milks()
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="بيض", qty=2)),
                          text_reply("ضفت بيض"))
    _turn(model, "ضيفي ٢ بيض للتسوق", pending=held)
    assert not _done(b), "«٢» picked the second milk and ticked it"
    assert model.seen, "the request itself never reached the model"
    assert "بيض" in _open("shopping")


def test_all_before_more_words_is_not_all(brain_db):  # noqa: F811
    a, b, held = _two_milks()
    _turn(ScriptedModel(text_reply("حلو")), "كل شي تمام", pending=held)
    assert not _done(a) and not _done(b), "«كل شي تمام» ticked both"


def test_a_pick_then_a_request_does_both(brain_db):  # noqa: F811
    from app.brain import confirm

    a, b, held = _two_milks()
    assert confirm.pick("التانية", held["candidates"]) == ([b], False)
    assert confirm.pick("الأولى والتالتة", held["candidates"])[0] == [a]
    assert confirm.pick("كلهم", held["candidates"]) == ([a, b], False)
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="خبز")),
                          text_reply("ضفت خبز"))
    state = _turn(model, "التانية وضيفي خبز", pending=held)
    assert _done(b) and not _done(a)
    assert "خبز" in _open("shopping") and "اختار" in model.seen[0][0]["content"]
    assert state["pending_state"] is None


# ── W7. A held delete does not swallow the answer to the rest of the line ────

def test_the_model_s_answer_stays_beside_the_held_question(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        gym = items.add("tasks", "روح عالجيم")
    model = ScriptedModel(tools_reply(call("list_update", id=gym, delete=True)),
                          text_reply("بكرا عندك اجتماع الساعة عشرة."))
    state = _turn(model, "احذفي مهمة الجيم وشو عندي بكرا؟")
    assert state["final_response"].startswith("بكرا عندك اجتماع الساعة عشرة.\nمتأكد إنك بدك تحذف"), \
        "tomorrow's answer was dropped and only the question came back"
    assert state["pending_state"] is not None


# ── W6. A message to your future self is in the reply, word for word ────────

def _due_message(text="لا تنسى تشرب مي"):
    from datetime import datetime, timedelta, timezone

    from app.blocks import schedules

    with active_user_profile_context(A):
        sid = schedules.add("message_to_future_self", text,
                            datetime.now(timezone.utc) + timedelta(minutes=5))
    from app.blocks import _base
    with active_user_profile_context(A):
        _base.coll(_base.SCHEDULES).update_one(
            {"_id": sid}, {"$set": {"fire_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    return sid


def _status(sid):
    from app.blocks import schedules
    with active_user_profile_context(A):
        return schedules.get(sid)["status"]


def test_a_future_message_rides_on_a_held_reply_word_for_word(brain_db):  # noqa: F811
    sid = _due_message()
    with active_user_profile_context(A):
        gym = items.add("tasks", "روح عالجيم")
    model = ScriptedModel(tools_reply(call("list_update", id=gym, delete=True)), text_reply(""))
    state = _turn(model, "احذفي مهمة الجيم")
    assert "لا تنسى تشرب مي" in state["final_response"], \
        "marked sent while the held reply never showed it"
    assert _status(sid) == "sent"
    assert all("لا تنسى تشرب مي" not in str(m.get("content")) for m in model.seen[0]), \
        "the model is never handed it, so it cannot say it twice"


def test_a_future_message_is_not_marked_when_the_turn_failed(brain_db):  # noqa: F811
    sid = _due_message()
    state = _turn(lambda *a, **k: None, "مرحبا")
    assert "لا تنسى" not in state["final_response"] and _status(sid) == "pending"


# ── W10. What an undo took back is not handed back by the same turn's save ────

def test_an_undo_written_again_finds_nothing_to_undo(brain_db):  # noqa: F811
    from app.brain import stm

    _turn(ScriptedModel(tools_reply(call("list_add", list="tasks", text="اشتري هدية")),
                        text_reply("ضفتها")), "ضيفي مهمة اشتري هدية")
    _turn(ScriptedModel(tools_reply(call("undo_last")), text_reply("رجّعت")), "لا غلط")
    assert "اشتري هدية" not in _open()
    # «Write it again» on the undo's reply: the reply goes, the same line is answered again.
    with active_user_profile_context(A):
        stm.rewind("userA", "userA", text="لا غلط")
    model = ScriptedModel(tools_reply(call("undo_last")), text_reply("ما في شي"))
    _turn(model, "لا غلط")
    tool_msgs = [m for m in model.seen[-1] if m.get("role") == "tool"]
    assert "nothing to undo" in tool_msgs[-1]["content"], \
        "the save handed the first reply its effects back, so they were undone twice"


# ── H2. A rewind takes back only the turn it names ───────────────────────────

import uuid  # noqa: E402

import mongomock  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    import app.db as appdb
    from app.api.auth_handlers import make_token
    from app.api.server import create_app
    from app.blocks import _base
    from app.brain import stm

    db = mongomock.MongoClient().db
    appdb.configure(db)
    monkeypatch.setattr(stm, "_stm_index_ready", True)
    undone = []
    monkeypatch.setattr(_base, "undo", lambda effects, *a, **k: undone.append(list(effects)) or 0)
    client = create_app(mongo_db=db).test_client()
    headers = {"Authorization": f"Bearer {make_token('user', user_id='u1')}"}
    yield client, headers, undone
    appdb.reset()


def _say(client, headers, cid, role, text, cmid=None):
    body = {"role": role, "text": text, **({"client_msg_id": cmid} if cmid else {})}
    assert client.post(f"/api/conversations/{cid}/messages", json=body,
                       headers=headers).status_code == 200


_ADDED = [{"op": "created", "coll": "sandy_items", "id": "x", "text": "حليب"}]


def test_editing_a_line_that_failed_leaves_the_turn_before_it_alone(api):
    from app.brain import stm

    client, headers, undone = api
    cid = uuid.uuid4().hex
    _say(client, headers, cid, "user", "ضيفي حليب", "a" * 32)
    _say(client, headers, cid, "sandy", "ضفت")
    stm.save(cid, "u1", "ضيفي حليب", "ضفت", effects=_ADDED, msg_id="a" * 32)
    _say(client, headers, cid, "user", "شو الطقس؟", "b" * 32)     # the turn failed: nothing saved
    client.post(f"/api/conversations/{cid}/rewind", json={}, headers=headers)
    assert [t["content"] for t in stm.load(cid, "u1")] == ["ضيفي حليب", "ضفت"], \
        "the milk turn was forgotten for a line that was never answered"
    assert not any(undone), "the milk Sandy added was deleted in silence"


def test_a_rewind_that_drops_nothing_touches_no_memory(api):
    from app.brain import stm

    client, headers, undone = api
    cid = uuid.uuid4().hex
    _say(client, headers, cid, "user", "ضيفي حليب", "a" * 32)
    _say(client, headers, cid, "sandy", "ضفت")
    stm.save(cid, "u1", "ضيفي حليب", "ضفت", effects=_ADDED, msg_id="a" * 32)
    _say(client, headers, cid, "user", "شو الطقس؟", "b" * 32)
    r = client.post(f"/api/conversations/{cid}/rewind", json={"keep_user": True}, headers=headers)
    assert r.get_json()["dropped"] == 0
    assert len(stm.load(cid, "u1")) == 2 and not any(undone)


def test_rewinding_the_answered_line_still_takes_it_back(api):
    from app.brain import stm

    client, headers, undone = api
    cid = uuid.uuid4().hex
    _say(client, headers, cid, "user", "ضيفي حليب", "a" * 32)
    _say(client, headers, cid, "sandy", "ضفت")
    stm.save(cid, "u1", "ضيفي حليب", "ضفت", effects=_ADDED, msg_id="a" * 32)
    client.post(f"/api/conversations/{cid}/rewind", json={"keep_user": True}, headers=headers)
    assert stm.load(cid, "u1") == [] and undone == [_ADDED]
