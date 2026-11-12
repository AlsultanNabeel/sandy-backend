"""The fast path of a fill (`browser_job._fast`, `brain/form_map.py`), tried before the agent:
the form's fields read once by the code, the model's table checked, every field filled at once
under the gate, then the send asked of him as the agent's click is and sent once on his yes; the
required fields he did not give asked together first; a form in steps, a table that cannot be
read, or a form that changes into another goes to the agent. Same safety as the agent's: his
values only, the gate on every field, his yes for the one send. Both languages."""
from __future__ import annotations

from pathlib import Path

import pytest
from brain_fakes import A, brain_db  # noqa: F401
from test_browser_fill import _job, _level, world  # noqa: F401

from app.brain import form_map, lang, tools
from app.brain.ctx import TurnCtx
from app.features import browser_job
from app.integrations import browser_cdp
from app.utils.user_profiles import active_user_profile_context

FORMS = Path(__file__).parent / "fixtures" / "forms"
URL = "https://forms.example.com/apply"


@pytest.fixture
def fast(world, monkeypatch):  # noqa: F811
    """The world's page is a saved form; the model's table is the test's."""
    world.pages, world.table, world.sets, world.agent_ran = [], [], [], []
    connect = browser_cdp.connect

    async def connected(url):
        client = await connect(url)
        evaluate, spot = client.answers["Runtime.evaluate"], client.answers["Runtime.callFunctionOn"]

        def evaluated(params, session):
            e = params["expression"]
            if e == form_map.FIELDS_JS:
                page = world.pages.pop(0) if len(world.pages) > 1 else (world.pages[0] if world.pages else "")
                return {"result": {"value": page}}
            if e.startswith("document.forms["):
                return {"result": {"objectId": "form0"}}
            return evaluate(params, session)

        def called(params, session):
            f = params["functionDeclaration"]
            if f == form_map.FIELD_OF_JS:
                return {"result": {"objectId": "field-" + params["arguments"][0]["value"]}}
            if f == form_map.SEND_OF_JS:
                return {"result": {"objectId": "send"}}
            if f == form_map.SET_JS:
                world.sets.append(params["arguments"][0]["value"])
                return {"result": {"value": True}}
            return spot(params, session)
        client.answers["Runtime.evaluate"] = evaluated
        client.answers["Runtime.callFunctionOn"] = called
        client.answers["DOM.describeNode"] = lambda params, session: {
            "node": {"backendNodeId": 7 if params["objectId"] == "send" else 3}}
        return client
    monkeypatch.setattr(browser_cdp, "connect", connected)
    monkeypatch.setattr(browser_job, "_mapped", lambda fields, goal, words, uid: list(world.table) if
                        world.table is not None else None)
    agent = browser_job.AGENT

    async def agent_ran(*args):
        world.agent_ran.append(1)
        return await agent(*args)
    monkeypatch.setattr(browser_job, "AGENT", agent_ran)
    return world


def _page(name):
    return (FORMS / name).read_text(encoding="utf-8")


def _fill(language, said, confirmed_job=None):
    with active_user_profile_context(A), lang.using(language):
        ctx = TurnCtx(user_id="userA", thread_id="t1", message=said)
        if confirmed_job:
            ctx.confirmed, ctx.held_ids = True, [confirmed_job]
        return tools.execute("page_fill", {"url": URL, "goal": "order", "details": ""}, ctx)


@pytest.mark.parametrize("language, said, name", [("ar", "عبّيلي النموذج، الاسم نبيل، الحجم لارج", "نبيل"),
                                                  ("en", "fill the form: name Nabeel, size large", "Nabeel")])
def test_a_simple_form_is_filled_at_once_asked_once_and_sent_once_on_his_yes(fast, language, said, name):
    _level("submit")
    fast.pages = [_page("httpbin.html")]
    fast.table = [{"field": "custname", "value": name}, {"field": "size", "value": "Large"}]
    fast.filled = [{"field": "Customer name", "value": name}, {"field": "Pizza Size", "value": "Large"}]
    asked = _fill(language, said)
    assert asked.get("needs_confirmation") and name in asked["summary"], asked
    assert fast.agent_ran == [] and fast.pressed == []
    assert fast.sets == [{"key": "custname", "kind": "text", "text": name},
                         {"key": "size", "kind": "radio", "values": ["large"], "labels": ["Large"]}]
    done = _fill(language, said, confirmed_job=asked["ids"][0])
    assert done["ok"] and "✅" in done["reply"]
    assert [kind for kind, _ in fast.pressed] == ["mouseMoved", "mousePressed", "mouseReleased"]
    assert _job(asked["ids"][0])["status"] == browser_job.DONE


@pytest.mark.parametrize("language, said, words", [("ar", "عبّيلي النموذج، الاسم نبيل", "ناقصني"),
                                                   ("en", "fill the form, name Nabeel", "I still need")])
def test_the_required_fields_he_did_not_give_are_asked_together_before_any_send(fast, language, said, words):
    _level("submit")
    fast.pages = [_page("form_missing.html")]
    fast.table = [{"field": "name", "value": "نبيل" if language == "ar" else "Nabeel"}]
    fast.filled = [{"field": "Name", "value": "x", "required": True}, {"field": "Email", "value": "", "required": True},
                   {"field": "Phone", "value": "", "required": True}]
    out = _fill(language, said)
    assert out["ok"] is False and words in out["reply"] and "«Email»" in out["reply"] and "«Phone»" in out["reply"]
    assert fast.agent_ran == [] and fast.pressed == []


def test_a_value_he_never_gave_is_never_written_and_is_asked_in_the_question(fast):
    _level("submit")
    fast.pages = [_page("httpbin.html")]
    fast.table = [{"field": "custname", "value": "Nabeel"}, {"field": "custtel", "value": "123-456-7890"}]
    asked = _fill("en", "fill it, name Nabeel")
    assert [s["key"] for s in fast.sets] == ["custname"]
    assert asked.get("needs_confirmation") and "Telephone" in asked["summary"]


@pytest.mark.parametrize("page", ["form_steps.html", "none"])
def test_a_form_in_steps_or_no_form_goes_to_the_agent(fast, page):
    _level("submit")
    fast.pages = [_page(page) if page != "none" else "<p>no form</p>"]
    asked = _fill("en", "fill it, name Nabeel")
    assert fast.agent_ran == [1] and fast.sets == [] and asked.get("needs_confirmation")


def test_a_table_that_cannot_be_read_goes_to_the_agent(fast):
    _level("submit")
    fast.pages = [_page("httpbin.html")]
    fast.table = None
    _fill("en", "fill it, name Nabeel")
    assert fast.agent_ran == [1] and fast.sets == []


def test_what_a_choice_shows_is_read_and_filled_before_he_is_asked(fast, monkeypatch):
    _level("submit")
    page = _page("form_reveals.html")
    fast.pages = [page, page.replace(' data-sandy-hidden="1"', "")]
    tables = [[{"field": "name", "value": "Nabeel"}, {"field": "topic", "value": "Other"}],
              [{"field": "other_topic", "value": "refund"}]]
    monkeypatch.setattr(browser_job, "_mapped", lambda fields, goal, words, uid: tables.pop(0))
    asked = _fill("en", "contact them: name Nabeel, topic other, other topic refund")
    assert [s["key"] for s in fast.sets] == ["name", "topic", "other_topic"]
    assert asked.get("needs_confirmation") and fast.agent_ran == []


def test_every_field_written_is_told_to_the_gate_first(fast, monkeypatch):
    from app.brain import browser_gate
    told = []
    acted = browser_gate.Gate.acted

    def watched(self, kind, text="", **kw):
        told.append((kind, text, len(fast.sets)))
        return acted(self, kind, text, **kw)
    monkeypatch.setattr(browser_gate.Gate, "acted", watched)
    _level("submit")
    fast.pages = [_page("httpbin.html")]
    fast.table = [{"field": "custname", "value": "Nabeel"}, {"field": "size", "value": "Large"}]
    _fill("en", "fill it: name Nabeel, size large")
    assert told[:2] == [("type", "Nabeel", 0), ("select", "Large", 1)]
