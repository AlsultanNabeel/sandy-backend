"""Three ways to reach Sandy, one memory.

The owner's test is the right one: ask her something out loud, then open the app
and ask a follow-up about the same thing. She should know what "it" is.

She did not. Not because anything was broken — every piece worked — but because
short-term memory is stored per conversation thread, and the three channels use
different threads:

    robot voice   -> /voice        -> thread = owner_id
    app voice     -> /voice        -> thread = owner_id      (same, correctly)
    app chat      -> /api/agent    -> thread = conversation_id

So the robot and the app's voice call already shared a memory. The app's text
chat had its own, and neither could see the other. Durable memory never had this
problem — it is keyed by person, not by thread — which is why she remembered
facts about him across channels but not the sentence he had just said.

These tests pin the fix: threads stay separate (a chat should not have another
chat's replies bleeding into it), and every channel can additionally see the
last few turns from anywhere.
"""
from __future__ import annotations

from pathlib import Path

import mongomock
import pytest

_ROOT = Path(__file__).resolve().parent.parent / "cloud/app"
_STM = (_ROOT / "brain/stm.py").read_text(encoding="utf-8")
_VOICE_MEM = (_ROOT / "api/voice_ws/memory.py").read_text(encoding="utf-8")


def test_the_voice_can_see_what_was_typed_in_the_app():
    assert "recent_turns_for_user" in _VOICE_MEM, (
        "the voice path reads only its own thread again — the robot cannot "
        "remember a conversation the owner had in the app a minute ago")
    assert "stm.load(chat_id, chat_id)" in _VOICE_MEM, (
        "the fallback for pre-existing documents is gone; anyone whose memory "
        "was written before `user_id` was stored starts from nothing")


def test_the_voice_prompt_keeps_the_past_record_guard():
    """Recent turns are safe to seed into a native-audio model only because the
    prompt says, in words, that they are a past record and not a live request."""
    tools = (_ROOT / "api/voice_ws/tools.py").read_text(encoding="utf-8")
    assert "سجلّ سابق للاطّلاع فقط" in tools


def test_every_turn_remembers_which_body_said_it():
    """He can ask "when did I tell you that?" and the answer should be real."""
    assert '"timestamp": ts, "via": via}' in _STM
    session = (_ROOT / "api/voice_ws/session.py").read_text(encoding="utf-8")
    assert 'set_voice_channel("الروبوت")' in session, (
        "the robot no longer tags its turns — it and the app's call share a "
        "socket, so without this they become indistinguishable in the record")
    assert '_APP_CHANNEL = "مكالمة التطبيق"' in session
    assert "set_voice_channel(_APP_CHANNEL)" in session
    assert 'f"[{via}] {role_label}: {content}"' in _VOICE_MEM, (
        "the source is recorded but never shown to her, which is the same as "
        "not recording it")


# ── Behaviour: one turn, said once, recalled on every channel ────────────────
#
#   robot voice  -> /voice, HMAC hello, identity = node.user_id  (session.py)
#   app voice    -> /voice, JWT hello,  identity = claims.user_id (session.py)
#   app chat     -> /api/agent, user_id = claims.user_id          (server.py)
#
# All three land on the same id, so what follows uses one id for all of them.

_UID = "one-memory-user"
_PROFILE = {"user_id": _UID, "chat_id": _UID, "relation": "user",
            "permissions": "all", "name": ""}


@pytest.fixture()
def store(monkeypatch):
    import app.db as appdb
    from app.brain import stm

    database = mongomock.MongoClient()["one_memory"]
    appdb.configure(database)
    monkeypatch.setattr(stm, "_stm_index_ready", True)  # mongomock: no TTL index
    try:
        yield database
    finally:
        appdb.reset()


def _robot_says(user_text, reply, uid=_UID):
    from app.api.voice_ws.memory import _save_voice_turn
    _save_voice_turn(user_text, reply, uid, "الروبوت")


def test_a_sentence_said_to_the_robot_is_known_to_the_app_chat_and_the_app_call(store):
    from app.api.voice_ws.memory import load_recent_turns
    from app.brain.stm import recent_turns_for_user

    _robot_says("اسم أخوي محمد", "حلو، تشرّفنا")

    chat_sees = [m["content"] for m in recent_turns_for_user(_UID, limit=6)]
    assert "اسم أخوي محمد" in chat_sees, "the app chat cannot see the robot's turn"

    call_sees = load_recent_turns(_UID)
    assert any(m["content"] == "اسم أخوي محمد" and m["via"] == "الروبوت"
               for m in call_sees), "the app's call cannot see the robot's turn"


def test_the_chat_sees_other_channels_once_and_keeps_its_own_thread(store):
    from app.brain import stm

    _robot_says("بكرا عندي مقابلة", "بالتوفيق")
    stm.save("conv-1", _UID, "شو لازم ألبس؟", "إشي رسمي", via="شات التطبيق")
    own, seen = stm.history("conv-1", _UID)
    assert [m["content"] for m in own] == ["شو لازم ألبس؟", "إشي رسمي"]
    contents = [m["content"] for m in seen]
    assert contents.count("شو لازم ألبس؟") == 1, "the thread's own line is shown twice"
    assert "بكرا عندي مقابلة" in contents, "the chat is blind to the robot"
    assert stm.load(_UID, _UID) != own, "threads were merged"


def test_a_sentence_typed_in_the_app_reaches_the_next_voice_call(store, monkeypatch):
    """Through the cache — which is where it used to die.

    The instruction is cached per tenant version, and a chat turn does not move
    the version. So the turns baked into the cached text were the ones from the
    call that built it: type in the app, call the robot, and she did not know.
    """
    import app.api.voice_ws.tools as vt
    from app.brain.stm import save

    vt.clear_instruction_cache()
    monkeypatch.setattr("app.utils.tenant_version.version_for", lambda t: 3)
    monkeypatch.setattr(vt, "_shared_get", lambda k, v: None)
    monkeypatch.setattr(vt, "_shared_put", lambda k, v, t: None)
    monkeypatch.setattr(vt, "_system_instruction_body",
                        lambda cid: "persona\n" + vt._PAST_RECORD_NOTE)

    vt._build_system_instruction(_UID)                       # the first call warms the cache
    save("conv-7", _UID, "بكرا عندي مقابلة", "بالتوفيق", via="شات التطبيق")
    text = vt._build_system_instruction(_UID)                # cache hit, same version

    assert "بكرا عندي مقابلة" in text, "the cached instruction froze the recent turns"
    assert "[شات التطبيق]" in text
    assert text.index("بكرا عندي مقابلة") < text.index(vt._PAST_RECORD_NOTE), (
        "the turns must sit above the 'past record, do not reply' guard")
    vt.clear_instruction_cache()


def test_a_pool_thread_does_not_lend_one_account_to_the_next(store):
    """Pool threads keep their context between jobs. With `if user_id:` an
    unpaired robot's turn was saved into whoever used the thread last."""
    from app.api.voice_ws.memory import load_recent_turns, set_voice_identity
    from app.brain.stm import recent_turns_for_user

    set_voice_identity(_UID)            # a previous session on this thread
    _robot_says("سرّ ما لحدا", "ماشي", uid="")   # an unpaired robot
    assert recent_turns_for_user(_UID) == [], "the stranger's turn landed in his memory"
    assert load_recent_turns("") == [], "the stranger was handed his memory"
    set_voice_identity("")


def test_she_knows_your_name_on_every_channel(store):
    """He typed his name at first open; chat and voice both read it from the one
    profile, and so do his answers to the daily questions."""
    import app.api.voice_ws.tools as vt
    from app.api.voice_ws.memory import set_voice_identity
    from app.brain import context

    store["sandy_users"].insert_one({"_id": _UID, "onboarding": {
        "preferred_name": "سامي", "interests": ["قهوة"],
        "nudge_answers": {"unwind": "المشي"}}})
    assert "سامي" in context.profile_block(_UID)
    set_voice_identity(_UID)
    try:
        text = vt._system_instruction_body(_UID)
    finally:
        set_voice_identity("")
    assert "«سامي»" in text and "قهوة" in text and "المشي" in text


def test_the_voice_seed_invents_nothing(store):
    """For a customer with nothing saved, the seed adds nothing about them."""
    import app.api.voice_ws.tools as vt
    from app.api.voice_ws.memory import set_voice_identity
    from app.utils.user_profiles import active_user_profile_context

    with active_user_profile_context(_PROFILE):
        set_voice_identity(_UID)
        text = vt._system_instruction_body(_UID)
    set_voice_identity("")
    assert "October City" not in text and "ملف المستخدم" not in text
    assert "معلومات بتعرفيها" not in text
