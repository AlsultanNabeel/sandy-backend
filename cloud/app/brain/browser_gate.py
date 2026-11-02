"""The network gate of a fill: nothing that sends leaves the browser without his yes, whatever the
model decided (`decide`).

It is our own connection to the session, apart from browser-use's (`install`): every tab, the
ones open now and any opened later (`Target.setAutoAttach` with `waitForDebuggerOnStart`, so a new
tab waits until the gate is on it), has `Fetch.enable` on it, and every request stops at the gate
first. A read (GET, HEAD, OPTIONS) goes on. A send (anything else) right after a click or Enter, to
the page's own site, is his: it is failed, kept as `held` with what was clicked, and the run stops
there for his yes (`features/browser_job`), its body and type with it. Any other send, an
analytics ping, an autosave as he types, another site, is failed and logged (`blocked`). A failed
form send leaves an error page where the form was (tried on Steel, 2 Nov 2026), so his yes does not
click again: the held send is made again from the form's page (`browser_job._send`), and `replay`
lets exactly that one through, its method to its address, once. `allow_one` lets one send to the site through. A
gate that cannot be put on (`GateError`) means no fill at all.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

GO, BLOCK, HOLD = "go", "block", "hold"
READS = ("GET", "HEAD", "OPTIONS")
# What the page sends right after these is his to approve; typing alone never is.
SENDING = ("click", "enter")
_PATTERNS = [{"urlPattern": "*", "requestStage": "Request"}]
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}


def _wire_errors() -> Tuple[type, ...]:
    from websockets.exceptions import WebSocketException
    return (OSError, RuntimeError, KeyError, TypeError, ValueError, asyncio.TimeoutError, WebSocketException)


_WIRE_ERRORS = _wire_errors()


class GateError(RuntimeError):
    """The gate could not be put on the session: the fill does not run."""


def _root(host: str) -> str:
    """The site a host belongs to, near enough: «forms.example.com» → «example.com»,
    «shop.example.co.uk» → «example.co.uk»."""
    labels = (host or "").lower().rstrip(".").split(".")
    take = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-take:])


class Gate:
    def __init__(self, site: str):
        self.site = _root(site)
        self.last: Optional[Dict[str, Any]] = None
        self.held: Optional[Dict[str, Any]] = None
        self.allowed = 0
        self.replaying: Optional[Tuple[str, str]] = None
        self.blocked: List[Tuple[str, str]] = []
        self.sent: List[Tuple[str, str]] = []

    def acted(self, kind: str) -> None:
        """What the model just did on the page: «click», «enter» or «type»."""
        self.last = {"kind": kind}

    def allow_one(self) -> None:
        """His yes: one send to the site goes."""
        self.allowed = 1

    def replay(self, held: Dict[str, Any]) -> None:
        """His yes: the held send, made again, goes once (its method to its address)."""
        self.replaying = (str(held.get("method") or "").upper(), str(held.get("url") or ""))

    def _own(self, url: str) -> bool:
        return _root(urlsplit(url).hostname or "") == self.site

    def decide(self, method: str, url: str, resource_type: str = "", *, body: str = "",
               content_type: str = "") -> str:
        method = str(method or "").upper()
        if method in READS:
            return GO
        if self.replaying == (method, url):
            self.replaying = None
            self.sent.append((method, url))
            return GO
        if self.allowed and self._own(url):
            self.allowed -= 1
            self.sent.append((method, url))
            return GO
        if self.held is None and self._own(url) and (self.last or {}).get("kind") in SENDING:
            self.held = {"method": method, "url": url, "body": body, "content_type": content_type}
            return HOLD
        self.blocked.append((method, url))
        return BLOCK


async def _cover(client, session: str) -> None:
    from app.integrations.browser_cdp import within
    await within(client.send.Fetch.enable(params={"patterns": _PATTERNS}, session_id=session))


async def install(client, gate: Gate) -> None:
    """The gate on every tab of the session, now and later, once per tab (two gates on one tab
    would each judge its requests; seen on Steel, 2 Nov 2026); GateError when it cannot be."""
    covered = set()

    def on_paused(event: Dict[str, Any], session: Optional[str] = None) -> None:
        request = event.get("request") or {}
        rid = event.get("requestId")
        headers = {str(k).lower(): v for k, v in (request.get("headers") or {}).items()}
        verdict = gate.decide(request.get("method", ""), request.get("url", ""), event.get("resourceType", ""),
                              body=str(request.get("postData") or ""), content_type=str(headers.get("content-type") or ""))
        if verdict == GO:
            reply = client.send.Fetch.continueRequest(params={"requestId": rid}, session_id=session)
        else:
            if verdict == BLOCK:
                logger.info("[browser] a send was blocked: %s", urlsplit(request.get("url", "")).hostname)
            reply = client.send.Fetch.failRequest(params={"requestId": rid, "errorReason": "BlockedByClient"},
                                                  session_id=session)
        asyncio.ensure_future(reply)

    def on_attached(event: Dict[str, Any], session: Optional[str] = None) -> None:
        new = event.get("sessionId")
        target = (event.get("targetInfo") or {}).get("targetId") or new
        if not new:
            return
        fresh = target not in covered
        covered.add(target)

        async def hold_then_go():
            if fresh:
                await _cover(client, new)
            if event.get("waitingForDebugger"):
                await client.send.Runtime.runIfWaitingForDebugger(session_id=new)
        asyncio.ensure_future(hold_then_go())

    try:
        client.register.Fetch.requestPaused(on_paused)
        client.register.Target.attachedToTarget(on_attached)
        from app.integrations.browser_cdp import within
        await within(client.send.Target.setAutoAttach(
            params={"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}))
        targets = (await within(client.send.Target.getTargets())).get("targetInfos") or []
        for t in targets:
            if t.get("type") != "page" or t["targetId"] in covered:
                continue
            covered.add(t["targetId"])
            session = (await within(client.send.Target.attachToTarget(
                params={"targetId": t["targetId"], "flatten": True})))["sessionId"]
            await _cover(client, session)
    except _WIRE_ERRORS as exc:  # whatever stops the gate stops the fill
        raise GateError(f"the gate could not be put on: {type(exc).__name__}") from exc
