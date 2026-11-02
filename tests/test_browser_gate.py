"""The network gate (`brain/browser_gate.py`), the safety net of a fill under the action's own
question. On the page's own site a read goes and a send goes only in the moment after his yes;
one right after a click he was not asked about stops the fill; his yes lets exactly one send
through, from the tab and frame he said yes to. From another site what a page
loads goes (a script, a style, a font, an image, media), and anything that sends is blocked. A
request to any other site that carries a value Sandy typed stops the fill, a GET for an image
too. Every target (tabs, frames, workers, old and new) waits until the gate is on it, websockets
are blocked and one made anyway stops the fill, and a gate that cannot be put on fails closed."""
from __future__ import annotations

import asyncio

import pytest
from cdp_fake import FakeCDP

from app.brain import browser_gate as G

URL_A = "https://forms.example.com/apply"
OTHER = "https://cdn.other.net"


def _gate(typed=("Nabeel Alsultan", "n@example.com")):
    gate = G.Gate("forms.example.com")
    for value in typed:
        gate.acted("type", value)
    gate.last = None
    return gate


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_the_sites_own_reads_go(method):
    assert _gate().decide(method, URL_A, "Document") == G.GO


@pytest.mark.parametrize("kind", ["Script", "Stylesheet", "Font", "Image", "Media"])
def test_what_a_page_loads_from_another_site_goes(kind):
    assert _gate().decide("GET", f"{OTHER}/asset", kind) == G.GO


@pytest.mark.parametrize("method, kind", [("GET", "XHR"), ("GET", "Fetch"), ("POST", "Ping"), ("GET", "Document"),
                                          ("POST", "Document"), ("POST", "Image"), ("GET", "EventSource"),
                                          ("GET", "Other")])
def test_what_sends_to_another_site_is_blocked_and_the_fill_goes_on(method, kind):
    gate = _gate()
    assert gate.decide(method, f"{OTHER}/collect?v=1", kind) == G.BLOCK
    assert gate.breach is None and gate.blocked == [(method, f"{OTHER}/collect?v=1")]


@pytest.mark.parametrize("url, body", [
    ("https://evil.example.org/p.gif?u=Nabeel%20Alsultan", ""),
    ("https://evil.example.org/p.gif?u=Nabeel+Alsultan", ""),
    ("https://evil.example.org/n@example.com.png", ""),
    ("https://evil.example.org/c", "email=n%40example.com"),
    ("https://evil.example.org/c", '{"name": "NABEEL ALSULTAN"}')])
def test_a_typed_value_to_another_site_stops_the_fill_even_an_image(url, body):
    stops = []
    gate = _gate()
    gate.on_breach = stops.append
    assert gate.decide("GET" if not body else "POST", url, "Image", body=body) == G.STOP
    assert gate.breach == G.LEAK and stops == [G.LEAK]


def test_a_short_value_is_too_common_to_tell_a_leak_by():
    gate = _gate(typed=("ok", "Nabeel Alsultan"))
    assert gate.decide("GET", f"{OTHER}/ok.png", "Image") == G.GO


def test_the_sites_own_send_waits_for_his_yes_and_typing_never_makes_it_his():
    gate = _gate()
    gate.acted("type", "Nabeel Alsultan")
    assert gate.decide("POST", "https://forms.example.com/autosave", "XHR") == G.BLOCK and gate.breach is None


@pytest.mark.parametrize("kind", ["click", "enter"])
def test_a_send_after_an_action_he_was_not_asked_about_stops_the_fill(kind):
    gate = _gate()
    gate.acted(kind)
    assert gate.decide("POST", URL_A, "Document") == G.STOP and gate.breach == G.UNASKED


def test_after_his_yes_one_send_goes_from_his_tab_and_frame_and_the_gate_shuts():
    gate = _gate()
    assert gate.decide("POST", URL_A, "Document", session="s1", frame="f1") == G.BLOCK
    gate.approve("s1", "f1")
    # Another tab or frame of the same page never takes his yes.
    assert gate.decide("POST", URL_A, "XHR", session="s2", frame="f1") == G.BLOCK
    assert gate.decide("POST", URL_A, "XHR", session="s1", frame="f2") == G.BLOCK
    assert gate.decide("POST", f"{OTHER}/x", "XHR", session="s1", frame="f1") == G.BLOCK
    assert gate.decide("POST", URL_A, "Document", session="s1", frame="f1") == G.GO
    # The one send went: the next, even at once from the same frame, is blocked.
    assert gate.decide("POST", "https://api.forms.example.com/x", "XHR", session="s1", frame="f1") == G.BLOCK
    assert gate.sent == [("POST", URL_A)]


def test_his_yes_left_unused_shuts_with_its_moment():
    gate = _gate()
    gate.approve("s1", "f1")
    gate.shut()
    assert gate.decide("POST", URL_A, "Document", session="s1", frame="f1") == G.BLOCK and gate.sent == []


def test_his_yes_never_lets_a_value_go_to_another_site():
    gate = _gate()
    gate.approve("s1", "f1")
    assert gate.decide("GET", "https://evil.example.org/?n=Nabeel+Alsultan", "Image", session="s1",
                       frame="f1") == G.STOP


def test_what_never_reaches_the_network_goes():
    assert _gate().decide("GET", "data:image/png;base64,Nabeel Alsultan", "Image") == G.GO


# ── On the wire ──

def test_every_target_waits_until_the_gate_is_on_it_and_websockets_are_blocked():
    client = FakeCDP()
    gate = _gate()
    asyncio.run(G.install(client, gate))
    auto = {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}
    assert ("Target.setAutoAttach", auto, None) in client.sent and ("Target.setAutoAttach", auto, "s1") in client.sent
    assert ("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}, "s1") in client.sent
    [blocked] = client.of("Network.setBlockedURLs")
    assert blocked["urls"] == ["ws://*", "wss://*"] and gate.sessions == {"t1": "s1"}

    async def more():
        for sid, kind in (("s2", "page"), ("s3", "iframe"), ("s4", "worker"), ("s5", "service_worker")):
            await client.fire("Target.attachedToTarget", {
                "sessionId": sid, "targetInfo": {"targetId": "t" + sid, "type": kind}, "waitingForDebugger": True})
    asyncio.run(more())
    names = [(n, sid) for n, _, sid in client.sent]
    for sid in ("s2", "s3", "s4", "s5"):
        assert names.index(("Fetch.enable", sid)) < names.index(("Runtime.runIfWaitingForDebugger", sid))
        assert names.index(("Network.setBlockedURLs", sid)) < names.index(("Runtime.runIfWaitingForDebugger", sid))
        assert ("Target.setAutoAttach", sid) in names
        assert names.index(("Runtime.evaluate", sid)) < names.index(("Runtime.runIfWaitingForDebugger", sid))
    # Pages and frames get it before every new document of theirs, with their page domain on.
    for sid in ("s2", "s3"):
        assert names.index(("Page.enable", sid)) < names.index(("Page.addScriptToEvaluateOnNewDocument", sid))
    assert {"source": G.NO_SOCKETS_JS, "runImmediately": True} in client.of("Page.addScriptToEvaluateOnNewDocument")
    assert ("Page.addScriptToEvaluateOnNewDocument", "s4") not in names
    assert gate.sessions == {"t1": "s1", "ts2": "s2"}


def test_a_target_the_gate_cannot_cover_stops_the_fill_and_never_runs():
    def refuse(params, session_id):
        if session_id == "s3":
            raise ConnectionError("gone")
        return {}
    client = FakeCDP({"Fetch.enable": refuse})
    gate = _gate()

    async def flow():
        await G.install(client, gate)
        await client.fire("Target.attachedToTarget", {"sessionId": "s3", "targetInfo": {"targetId": "t3", "type": "iframe"},
                                                      "waitingForDebugger": True})
    asyncio.run(flow())
    assert gate.breach == "uncovered" and ("Runtime.runIfWaitingForDebugger", "s3") not in [
        (n, sid) for n, _, sid in client.sent]


def test_a_websocket_made_anyway_stops_the_fill():
    client = FakeCDP()
    gate = _gate()

    async def flow():
        await G.install(client, gate)
        await client.fire("Network.webSocketCreated", {"requestId": "w1", "url": "wss://evil.example.org/s"}, "s1")
    asyncio.run(flow())
    assert gate.breach == G.SOCKET


def test_a_paused_request_is_answered_as_the_gate_decides():
    client = FakeCDP()
    gate = _gate()

    async def flow():
        await G.install(client, gate)
        for rid, method, url, kind in (("r1", "GET", URL_A, "Document"), ("r2", "GET", f"{OTHER}/f.woff2", "Font"),
                                       ("r3", "POST", f"{OTHER}/collect", "Ping"),
                                       ("r4", "GET", "https://evil.example.org/?e=n@example.com", "Image")):
            await client.fire("Fetch.requestPaused", {"requestId": rid, "resourceType": kind,
                                                      "request": {"method": method, "url": url}}, "s1")
    asyncio.run(flow())
    assert client.of("Fetch.continueRequest") == [{"requestId": "r1"}, {"requestId": "r2"}]
    assert client.of("Fetch.failRequest") == [{"requestId": "r3", "errorReason": "BlockedByClient"},
                                              {"requestId": "r4", "errorReason": "BlockedByClient"}]
    assert gate.breach == G.LEAK


def test_a_gate_that_cannot_be_put_on_fails_closed():
    def refuse(params, session_id):
        raise ConnectionError("one connection only")
    client = FakeCDP({"Target.setAutoAttach": refuse})
    with pytest.raises(G.GateError):
        asyncio.run(G.install(client, _gate()))


def test_a_tab_gets_one_gate_even_when_it_is_attached_twice():
    """Auto-attach also attaches the tabs already open: a second gate on a tab would judge its
    requests twice."""
    client = FakeCDP()

    async def flow():
        await G.install(client, _gate())
        await client.fire("Target.attachedToTarget", {"sessionId": "s9", "targetInfo": {"targetId": "t1", "type": "page"},
                                                      "waitingForDebugger": False})
    asyncio.run(flow())
    assert [sid for name, _, sid in client.sent if name == "Fetch.enable"] == ["s1"]
