"""A fill (`features/browser_job.py`, `tools_browser.page_fill`, behind the `browser` switch): a
read-only site is refused; otherwise browser-use fills it in a Steel session of his own behind the
gate, and the send it tries is held: on a site he lets her send, his yes sends it once and the
next page is the answer; on a fill-only site the page is handed to him. A field she must never
touch stops it; no gate, no fill; a fill that outlasts the wait goes on in the background and
leaves its question on his chat; the emergency stop and «خليني أكمّل أنا» stop it. Steel's live
view reaches only his own fill. In both languages, the agent itself a stand-in (no Steel here)."""
from __future__ import annotations

import asyncio
import base64
import json
import time
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401
from cdp_fake import FakeCDP

from app import notify
from app.brain import browser_guard, lang, loop, pending, tools
from app.brain.ctx import TurnCtx
from app.features import browser_job, browser_sites, stop_all
from app.integrations import browser_cdp, steel_client
from app.utils.user_profiles import active_user_profile_context

URL = "https://forms.example.com/apply"
FORM = {"url": URL, "fields": [{"type": "text", "name": "name"}, {"type": "email", "name": "email"}],
        "frames": [], "marks": []}
ARGS = {"url": URL, "goal": "apply for the course", "details": "Name: Nabeel, email: n@example.com"}


@pytest.fixture
def world(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"browser": ["userA"]}')
    monkeypatch.setenv("SANDY_LTM_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    monkeypatch.setattr(steel_client.config, "STEEL_API_KEY", "k")
    brain_db["sandy_users"].insert_one({"_id": "userA"})
    browser_sites.init_browser_sites(brain_db)
    w = NS(snapshot=FORM, clients=[], opened=[], released=[], mode="submit", sent_notes=[],
           result="<html><body><main><p>Thanks Nabeel, your application 77 was received.</p></main></body></html>")

    def evaluate(client):
        def answer(params, session):
            e = params["expression"]
            if e == "document.readyState":
                value = "complete"
            elif e == browser_guard.SNAPSHOT_JS:
                value = json.dumps(w.snapshot)
            elif e == browser_job._FILLED_JS:
                value = [{"field": "Name", "value": "Nabeel"}, {"field": "Email", "value": "n@example.com"}]
            elif "outerHTML" in e:
                value = w.result
            elif e == "location.href":
                value = URL + "/thanks"
            elif "el.click()" in e:
                # The click sends the form: the gate sees it.
                client.handlers["Fetch.requestPaused"]({"requestId": "r9", "resourceType": "Document",
                                                        "request": {"method": "POST", "url": URL}}, "s1")
                value = True
            else:
                value = True
            return {"result": {"value": value}}
        return answer

    async def connect(url):
        client = FakeCDP()
        client.answers["Runtime.evaluate"] = evaluate(client)
        w.clients.append(client)
        return client

    async def agent(row, gate, client, tab, user_id):
        deadline = time.monotonic() + (3 if w.mode == "slow" else 0)
        while time.monotonic() < deadline:
            now = browser_job.get(row["_id"]) or {}
            if now.get("status") in (browser_job.STOPPED, browser_job.HANDED):
                return {"status": now["status"]}
            await asyncio.sleep(0.05)
        gate.acted("type", xpath="//input[1]")
        gate.decide("POST", "https://forms.example.com/validate", "XHR")
        gate.acted("click", xpath="//form/button[1]")
        gate.decide("POST", URL, "Document")
        return {"status": browser_job.DONE, "result": ""}

    monkeypatch.setattr(browser_cdp, "connect", connect)
    monkeypatch.setattr(browser_job, "AGENT", agent)
    monkeypatch.setattr(steel_client, "create_session", lambda: w.opened.append(1) or {
        "id": f"st{len(w.opened)}", "debug_url": "https://api.steel.dev/v1/sessions/st1/player"})
    monkeypatch.setattr(steel_client, "release", lambda sid, seconds=0: w.released.append(sid))
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: w.sent_notes.append(r["body"])])
    return w


def _level(level):
    with active_user_profile_context(A):
        browser_sites.set_level("forms.example.com", level)


def _fill(language="ar", confirmed_job=None, thread="t1"):
    with active_user_profile_context(A), lang.using(language):
        ctx = TurnCtx(user_id="userA", thread_id=thread)
        if confirmed_job:
            ctx.confirmed, ctx.held_ids = True, [confirmed_job]
        return tools.execute("page_fill", dict(ARGS), ctx)


def _job(job_id):
    with active_user_profile_context(A):
        return browser_job.get(job_id)


@pytest.mark.parametrize("language, words", [("ar", "مسموحلي أقرا بس"), ("en", "may only read")])
def test_a_read_only_site_is_never_filled(world, language, words):
    out = _fill(language)
    assert out["ok"] is False and words in out["reply"] and world.opened == []


@pytest.mark.parametrize("language", ["ar", "en"])
def test_the_send_waits_for_his_yes_and_then_goes_once(world, language):
    _level("submit")
    asked = _fill(language)
    assert asked["needs_confirmation"] and "Name: Nabeel" in asked["summary"]
    [job] = asked["ids"]
    assert _job(job)["status"] == browser_job.HELD and world.released == []
    done = _fill(language, confirmed_job=job)
    assert done["ok"] and "application 77 was received" in done["reply"]
    sender = world.clients[-1]
    assert sender.of("Fetch.continueRequest") == [{"requestId": "r9"}]
    assert _job(job)["status"] == browser_job.DONE and world.released == ["st1"]


def test_his_yes_on_a_fill_that_is_gone_says_so(world):
    _level("submit")
    out = _fill("en", confirmed_job="nope")
    assert out["ok"] is False and "isn't waiting" in out["reply"]


@pytest.mark.parametrize("language, words", [("ar", "وما بعتته"), ("en", "didn't send it")])
def test_a_fill_only_site_hands_him_the_page_and_never_sends(world, language, words):
    _level("fill")
    out = _fill(language)
    assert out["ok"] and words in out["reply"] and "sandy://browser/live?job=" in out["reply"]
    assert _job(out["job"])["status"] == browser_job.HANDED


@pytest.mark.parametrize("why", ["password", "card", "captcha", "payment"])
def test_a_field_she_must_never_touch_stops_the_fill(world, why):
    _level("submit")
    world.snapshot = {**FORM, "fields": [{"type": "password"}]} if why == "password" else \
        {**FORM, "fields": [{"autocomplete": "cc-number"}]} if why == "card" else \
        {**FORM, "marks": ["g-recaptcha"]} if why == "captcha" else {**FORM, "url": "https://forms.example.com/checkout"}
    out = _fill("en")
    assert out["ok"] is False and "I stopped" in out["reply"] and world.released == ["st1"]


def test_no_gate_no_fill(world, monkeypatch):
    _level("submit")
    from app.brain import browser_gate

    async def refuse(client, gate):
        raise browser_gate.GateError("one connection only")
    monkeypatch.setattr(browser_gate, "install", refuse)
    monkeypatch.setattr(browser_job, "AGENT", lambda *a: pytest.fail("the agent ran"))
    out = _fill("en")
    assert out["ok"] is False and world.released == ["st1"]


def test_a_slow_fill_goes_on_in_the_background_and_leaves_its_question_on_his_chat(world, monkeypatch, brain_db):  # noqa: F811
    _level("submit")
    world.mode = "slow"
    monkeypatch.setattr(browser_job, "WAIT_S", 0.3)
    out = _fill("en", thread="t9")
    assert out["ok"] and "in the background" in out["reply"] and "sandy://browser/live?job=" in out["reply"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not world.sent_notes:
        time.sleep(0.1)
    assert world.sent_notes and "Are you sure you want to send the form" in world.sent_notes[0]
    held = pending.load("t9", "userA", brain_db)
    assert held["steps"][0]["tool"] == "page_fill" and held["steps"][0]["ids"] == [out["job"]]


def test_the_emergency_stop_stops_a_running_fill(world, monkeypatch):
    _level("submit")
    world.mode = "slow"
    monkeypatch.setattr(browser_job, "WAIT_S", 0.3)
    out = _fill("en")
    with active_user_profile_context(A):
        stop_all.stop("userA")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and "st1" not in world.released:
        time.sleep(0.1)
    assert _job(out["job"])["status"] == browser_job.STOPPED and world.released == ["st1"]
    with active_user_profile_context(A):
        stop_all.resume("userA")


@pytest.mark.parametrize("language, said, yes", [("ar", "عبّيلي هالنموذج " + URL, "اه"),
                                                 ("en", "fill this form " + URL, "yes")])
def test_in_a_turn_the_yes_sends_it(world, language, said, yes):
    _level("submit")
    model = ScriptedModel(tools_reply(call("page_fill", **ARGS)), text_reply("..."))
    with active_user_profile_context(A):
        first = loop.run_turn(said, user_id="userA", chat_id="userA", source="web", complete=model)
        assert first["pending_state"] and "Nabeel" in first["final_response"]
        second = loop.run_turn(yes, user_id="userA", chat_id="userA", source="web",
                               pending_state=first["pending_state"], complete=ScriptedModel(text_reply("ok")))
    assert "application 77" in second["final_response"]


# ── «متصفح ساندي» ──

@pytest.fixture
def client(world, brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    return create_app(mongo_db=brain_db).test_client()


def _h(uid="userA"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def test_the_live_view_is_watch_only_and_his_alone_until_he_takes_over(world, client, monkeypatch):
    _level("submit")
    asked = _fill("en")
    job = asked["ids"][0]
    assert [j["id"] for j in client.get("/api/browser/jobs", headers=_h()).get_json()["jobs"]] == [job]
    live = client.get(f"/api/browser/jobs/{job}/live", headers=_h()).get_json()
    assert live["url"].endswith("?interactive=false&showControls=false") and live["control"] is False
    monkeypatch.setenv("SANDY_FLAGS", '{"browser": ["userA", "userB"]}')
    assert client.get(f"/api/browser/jobs/{job}/live", headers=_h("userB")).status_code == 404
    took = client.post(f"/api/browser/jobs/{job}/takeover", headers=_h()).get_json()
    assert took["url"].endswith("?interactive=true&showControls=true")
    assert _job(job)["status"] == browser_job.HANDED


def test_what_she_did_on_the_page_is_on_the_runs_trace(world, brain_db):  # noqa: F811
    _level("submit")
    _fill("en")
    rows = list(brain_db["sandy_traces"].find({"source": {"$exists": True}}))
    names = [t["name"] for r in rows for t in r.get("tools", [])]
    assert "browser_open" in names and "browser_blocked" in names and "browser_held" in names


def test_the_real_agent_is_built_on_our_model_the_sites_domains_and_the_gate(monkeypatch):
    """browser-use's own agent, constructed as a fill builds it (no browser runs here)."""
    import browser_use
    from browser_use.browser import events

    from app.brain import browser_gate
    from app.brain.browser_llm import SandyLLM
    built, handlers = {}, []

    class Session:
        def __init__(self, **kw):
            built["session"] = kw
            self.event_bus = NS(on=lambda kind, fn: handlers.append((kind, fn)))

        async def stop(self):
            built["stopped"] = True

    class Agent:
        def __init__(self, **kw):
            built["agent"] = kw

        async def run(self, max_steps):
            built["steps"] = max_steps
            return NS(final_result=lambda: "filled")
    monkeypatch.setattr(browser_use, "Agent", Agent)
    monkeypatch.setattr(browser_use, "BrowserSession", Session)
    monkeypatch.setattr(steel_client.config, "STEEL_API_KEY", "k")
    row = {"_id": "j1", "site": "forms.example.com", "steel_id": "st1", "goal": "apply", "args": {"details": "Name: N"}}
    gate = browser_gate.Gate("forms.example.com")
    out = asyncio.run(browser_job._agent(row, gate, FakeCDP(), "s1", "userA"))
    assert out == {"status": browser_job.DONE, "result": "filled"} and built["stopped"]
    assert built["session"]["allowed_domains"] == ["forms.example.com", "*.forms.example.com"]
    agent = built["agent"]
    assert isinstance(agent["llm"], SandyLLM) and agent["use_judge"] is False and built["steps"] == browser_job.MAX_STEPS
    excluded = set(agent["tools"].registry.registry.actions)
    assert not excluded & {"evaluate", "navigate", "search", "upload_file"} and {"click", "input"} <= excluded
    assert {k for k, _ in handlers} == {events.ClickElementEvent, events.TypeTextEvent, events.SendKeysEvent,
                                        events.ClickCoordinateEvent}
    # A click the agent is about to make is the gate's to know.
    dict(handlers)[events.ClickElementEvent](NS(node=NS(xpath="//button[1]", attributes={"name": "go"})))
    assert gate.last == {"kind": "click", "xpath": "//button[1]"}
