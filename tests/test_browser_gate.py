"""The network gate (`brain/browser_gate.py`): in a fill, nothing that sends leaves the browser
without his yes, whatever the model decided. Reads go; a send right after a click or Enter on the
page's own site stops the run and keeps what was clicked; any other send (analytics, an autosave,
another site) is blocked and logged; after his yes exactly one send to the site goes. Every tab,
even one opened later, is held until the gate is on it; and a gate that cannot be put on fails
the fill closed."""
from __future__ import annotations

import asyncio

import pytest
from cdp_fake import FakeCDP

from app.brain import browser_gate as G


def _gate():
    return G.Gate("forms.example.com")


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_reads_go(method):
    assert _gate().decide(method, "https://forms.example.com/x", "Document") == G.GO


def test_a_send_with_nothing_clicked_is_blocked_not_a_stop():
    gate = _gate()
    assert gate.decide("POST", "https://forms.example.com/autosave", "XHR") == G.BLOCK
    assert gate.held is None and gate.blocked == [("POST", "https://forms.example.com/autosave")]


def test_a_send_after_a_click_on_the_site_stops_the_run_and_keeps_what_was_clicked():
    gate = _gate()
    gate.acted("click", xpath="//form/button[1]")
    assert gate.decide("POST", "https://forms.example.com/apply", "Document") == G.HOLD
    assert gate.held == {"method": "POST", "url": "https://forms.example.com/apply",
                         "action": {"kind": "click", "xpath": "//form/button[1]"}}
    # Once held, everything else that sends is blocked until his yes.
    assert gate.decide("POST", "https://forms.example.com/apply", "XHR") == G.BLOCK


def test_enter_in_a_field_counts_as_a_send():
    gate = _gate()
    gate.acted("enter", xpath="//input[@name='q']")
    assert gate.decide("POST", "https://www.forms.example.com/search", "Fetch") == G.HOLD


def test_typing_alone_never_makes_a_send_his():
    gate = _gate()
    gate.acted("type", xpath="//input[1]")
    assert gate.decide("POST", "https://forms.example.com/validate", "XHR") == G.BLOCK


def test_another_sites_send_is_blocked_even_after_a_click():
    gate = _gate()
    gate.acted("click", xpath="//button")
    assert gate.decide("POST", "https://www.google-analytics.com/collect", "Ping") == G.BLOCK
    assert gate.held is None


def test_after_his_yes_exactly_one_send_goes():
    gate = _gate()
    gate.allow_one()
    assert gate.decide("POST", "https://forms.example.com/apply", "Document") == G.GO
    assert gate.sent == [("POST", "https://forms.example.com/apply")]
    assert gate.decide("POST", "https://forms.example.com/apply", "Document") == G.BLOCK


def test_the_one_send_he_allowed_is_never_spent_on_another_site():
    gate = _gate()
    gate.allow_one()
    assert gate.decide("POST", "https://evil.example.net/steal", "XHR") == G.BLOCK
    assert gate.decide("POST", "https://forms.example.com/apply", "Document") == G.GO


# ── On the wire ──

def test_the_gate_holds_every_tab_old_and_new_until_it_is_on_it():
    client = FakeCDP()
    gate = _gate()
    asyncio.run(G.install(client, gate))
    [auto] = client.of("Target.setAutoAttach")
    assert auto == {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}
    assert ("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}, "s1") in client.sent

    async def a_new_tab():
        await client.fire("Target.attachedToTarget",
                          {"sessionId": "s2", "targetInfo": {"targetId": "t2", "type": "page"}, "waitingForDebugger": True})
    asyncio.run(a_new_tab())
    names = [(n, sid) for n, _, sid in client.sent]
    assert names.index(("Fetch.enable", "s2")) < names.index(("Runtime.runIfWaitingForDebugger", "s2"))


def test_a_paused_request_is_answered_as_the_gate_decides():
    client = FakeCDP()
    gate = _gate()

    async def flow():
        await G.install(client, gate)
        await client.fire("Fetch.requestPaused", {"requestId": "r1", "resourceType": "Document",
                                                  "request": {"method": "GET", "url": "https://forms.example.com/"}}, "s1")
        gate.acted("click", xpath="//button")
        await client.fire("Fetch.requestPaused", {"requestId": "r2", "resourceType": "Document",
                                                  "request": {"method": "POST", "url": "https://forms.example.com/a"}}, "s1")
    asyncio.run(flow())
    assert client.of("Fetch.continueRequest") == [{"requestId": "r1"}]
    assert client.of("Fetch.failRequest") == [{"requestId": "r2", "errorReason": "BlockedByClient"}]
    assert gate.held["url"] == "https://forms.example.com/a"


def test_a_gate_that_cannot_be_put_on_fails_closed():
    def refuse(params, session_id):
        raise ConnectionError("one connection only")
    client = FakeCDP({"Target.setAutoAttach": refuse})
    with pytest.raises(G.GateError):
        asyncio.run(G.install(client, _gate()))
