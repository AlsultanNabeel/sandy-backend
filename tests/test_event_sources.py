"""Every event says where the change came from (owner, 30 Oct 2026): the chat, the app's
call, the robot's call, the app's own screens, or the system; tested from each, in both
languages."""
from __future__ import annotations



import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import events, items
from app.brain import loop
from app.utils.user_profiles import active_user_profile_context


def _sources():
    with active_user_profile_context(A):
        return [e["source"] for e in events.since(0)]


@pytest.mark.parametrize("message", ["ضيفي رمان", "add pomegranate"])
def test_the_chat(brain_db, message):  # noqa: F811
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="رمان")), text_reply("ok"))
    with active_user_profile_context(A):
        loop.run_turn(message, user_id="userA", chat_id="userA", source="web", complete=model)
    assert _sources() == ["chat"]


@pytest.mark.parametrize("channel, source", [("app", "voice"), ("robot", "robot")])
@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_call_the_apps_and_the_robots(brain_db, channel, source, language):  # noqa: F811
    from app.api.voice_ws.tools import _dispatch_tool
    out = _dispatch_tool("list_add", {"list": "shopping", "text": "رمان"}, "userA", "t1",
                         language=language, channel=channel)
    assert out.get("ok") is not False and _sources() == [source]


def test_the_apps_screens(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.auth_handlers import make_token
    from app.api.server import create_app
    c = create_app(mongo_db=brain_db).test_client()
    h = {"Authorization": f"Bearer {make_token('user', user_id='userA')}"}
    r = c.post("/api/items", headers=h, json={"list": "shopping", "text": "رمان"})
    assert r.status_code == 200 and _sources() == ["app"]


def test_anything_else_is_the_system(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        items.add("shopping", "رمان")
    assert _sources() == ["system"]


def test_an_unknown_source_is_refused():
    with pytest.raises(ValueError):
        with events.using_source("telepathy"):
            pass
