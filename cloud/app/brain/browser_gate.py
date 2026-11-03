"""The network gate of a fill: a safety net under the action's own question
(`features/browser_job`, which stops before a click or an Enter that sends and asks him first).

It is our own connection to the session, apart from browser-use's (`install`): every target, the
tabs open now and every tab, frame and worker attached later (`Target.setAutoAttach` with
`waitForDebuggerOnStart` on the browser and on each target, so each one waits until the gate is
on it), has `Fetch.enable` on it, no websocket or peer connection in its scripts (`NO_SOCKETS_JS`,
before the page's own), websockets blocked (`Network.setBlockedURLs`) and watched
(`Network.webSocketCreated`), and every request stops at the gate first (`decide`):

  * the page's own site: a read goes; after his yes (`approve`) exactly one send goes, the first
    from the tab and frame he said yes to once the click is made, and the gate shuts behind it;
    a request right after a click or a key the agent made (`acted`) is held, kept paused and not
    answered, and the fill asks him about it (`HOLD`, `on_hold`): any send, and once Sandy typed
    a value any read too (a link with its query, a script's fetch), what a page loads aside; any
    other send is failed and logged;
  * another site: what a page loads goes (a script, a style, a font, an image, media, by GET);
    anything that sends (a fetch, a beacon, a form, a frame, any method but GET) is failed and
    logged;
  * any site but the page's own: a request whose address or body carries a value Sandy typed on
    the page (`typed`) is failed and stops the fill (`LEAK`), a GET for an image too.

A stop (`breach`) is told to the fill at once (`on_breach`), which closes the session and tells
him. A gate that cannot be put on (`GateError`) means no fill at all.
"""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, quote_plus, unquote_plus, urlsplit

logger = logging.getLogger(__name__)

GO, BLOCK, STOP, HOLD = "go", "block", "stop", "hold"
LEAK, SOCKET = "leak", "socket"
READS = ("GET", "HEAD", "OPTIONS")
# What a page loads from anywhere: never a send.
LOADS = ("Script", "Stylesheet", "Font", "Image", "Media")
# What follows these on the page's own site is held for him: a click, an Enter or any other key.
SENDING = ("click", "enter", "keys")
# A typed value shorter than this is too common to tell a leak by («1», «ok»).
MIN_TYPED = 3
_NO_NETWORK = ("data:", "blob:", "about:")
_PATTERNS = [{"urlPattern": "*", "requestStage": "Request"}]
_SOCKETS = {"urls": ["ws://*", "wss://*"],
            "urlPatterns": [{"urlPattern": "ws://*:*/*", "block": True}, {"urlPattern": "wss://*:*/*", "block": True}]}
# Run in every page, frame and worker before its own scripts: no websocket, no peer connection
# (each a way out the network gate never sees: tried on Steel, 2 Nov 2026, a blocked websocket
# still opened).
NO_SOCKETS_JS = """(() => { const no = function () { throw new DOMException("blocked", "SecurityError"); };
  for (const name of ["WebSocket", "WebTransport", "RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel"]) {
    try { Object.defineProperty(globalThis, name, {value: no, writable: false, configurable: false}); } catch (e) {} }
})()"""
_FRAMES = ("page", "iframe")


def _wire_errors() -> Tuple[type, ...]:
    from websockets.exceptions import WebSocketException
    return (OSError, RuntimeError, KeyError, TypeError, ValueError, asyncio.TimeoutError, WebSocketException)


_WIRE_ERRORS = _wire_errors()


class GateError(RuntimeError):
    """The gate could not be put on the session: the fill does not run."""


@functools.lru_cache(maxsize=1)
def _suffixes():
    from publicsuffixlist import PublicSuffixList
    # The list's private part too: «a.netlify.app» and «b.netlify.app» are two sites.
    return PublicSuffixList()


def _root(host: str) -> str:
    """The site a host belongs to, by the public suffix list: «forms.example.com» → «example.com»,
    «shop.example.co.uk» → «example.co.uk», «a.netlify.app» → itself; an address is its own."""
    host = (host or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host
    except ValueError:
        pass
    return _suffixes().privatesuffix(host) or host


def root_of(url: str) -> str:
    return _root(urlsplit(str(url or "")).hostname or "")


class Gate:
    def __init__(self, site: str):
        self.site = _root(site)
        self.last: Optional[str] = None
        self.typed: Set[str] = set()
        # Whether Sandy typed on the page yet: from then on a read after a click is held too.
        self.wrote = False
        # A page he took over: what he sends to its own site goes (`browser_job._handing`).
        self.his = False
        # The one request held for him ({session, request, method, url}) and who is told of it.
        self.paused: Optional[Dict[str, str]] = None
        self.on_hold: Optional[Callable[[Dict[str, str]], None]] = None
        # The tab and frame whose one send his yes lets through, until it goes (`approve`).
        self.armed: Optional[Tuple[str, str]] = None
        self.breach: Optional[str] = None
        self.on_breach: Optional[Callable[[str], None]] = None
        self.blocked: List[Tuple[str, str]] = []
        self.sent: List[Tuple[str, str]] = []
        # Each page's own session on our connection, by its target (the real click is made there).
        self.sessions: Dict[str, str] = {}

    def acted(self, kind: str, text: str = "") -> None:
        """What the model just did on the page: «click», «enter», «keys» or «type» (with what it
        typed)."""
        self.last = kind
        if kind == "type":
            self.wrote = True
            self.watch(text)

    def watch(self, text: str) -> None:
        """A value of his that must never reach another site (what Sandy will type)."""
        for value in (str(text or ""), *str(text or "").split()):
            if len(value.strip()) >= MIN_TYPED:
                self.typed.add(value.strip())

    def let_paused(self) -> Optional[Dict[str, str]]:
        """His yes on the held request: it goes, once."""
        paused, self.paused = self.paused, None
        if paused is not None:
            self.sent.append((paused["method"], paused["url"]))
        return paused

    def approve(self, session: str, frame: str) -> None:
        """His yes, made as the click is: the first send to its own site from this tab
        (``session``) and frame goes, and none after it (`shut`)."""
        self.armed = (str(session or ""), str(frame or ""))
        self.last = None

    def shut(self) -> None:
        """The moment of his yes is over, whether its send went or not."""
        self.armed = None

    def stop(self, why: str) -> None:
        if self.breach is None:
            self.breach = why
            logger.warning("[browser] a fill was stopped by its gate: %s", why)
            if self.on_breach is not None:
                self.on_breach(why)

    def _hold(self, method: str, url: str, session: str, request: str) -> str:
        """A request the agent's click or key made: held for him, the first one; any after it
        while he is asked is blocked."""
        if self.paused is not None or not request:
            self.blocked.append((method, url))
            return BLOCK
        self.paused = {"session": str(session or ""), "request": str(request), "method": method, "url": url}
        logger.info("[browser] a request was held for him: %s", urlsplit(url).hostname)
        if self.on_hold is not None:
            self.on_hold(self.paused)
        return HOLD

    def _carries(self, url: str, body: str) -> bool:
        """Whether a request carries a value Sandy typed, as typed or encoded."""
        seen = f"{url}\n{unquote_plus(url)}\n{body}\n{unquote_plus(body)}".lower()
        return any(form.lower() in seen for value in self.typed
                   for form in (value, quote(value, safe=""), quote_plus(value)))

    def decide(self, method: str, url: str, resource_type: str = "", *, body: str = "",
               session: str = "", frame: str = "", request: str = "") -> str:
        method, url = str(method or "").upper(), str(url or "")
        if url.startswith(_NO_NETWORK):
            return GO
        own = root_of(url) == self.site
        if not own and self._carries(url, body):
            self.blocked.append((method, url))
            self.stop(LEAK)
            return STOP
        if own and self.his:
            return GO
        if own:
            if self.armed is not None and self.armed == (str(session or ""), str(frame or "")):
                self.armed = None
                self.sent.append((method, url))
                return GO
            loads = method == "GET" and resource_type in LOADS
            if self.last in SENDING and not loads and (method not in READS or self.wrote):
                return self._hold(method, url, session, request)
            if method in READS:
                return GO
            self.blocked.append((method, url))
            return BLOCK
        if method == "GET" and resource_type in LOADS:
            return GO
        self.blocked.append((method, url))
        return BLOCK


async def _cover(client, gate: Gate, session: str, kind: str = "page") -> None:
    """The gate on one target, and on whatever it opens next (its frames and workers)."""
    from app.integrations.browser_cdp import within
    if kind in _FRAMES:
        # A script for new documents runs only where the page domain is on.
        await within(client.send.Page.enable(params={}, session_id=session))
        await within(client.send.Page.addScriptToEvaluateOnNewDocument(
            params={"source": NO_SOCKETS_JS, "runImmediately": True}, session_id=session))
    await within(client.send.Runtime.evaluate(params={"expression": NO_SOCKETS_JS}, session_id=session))
    await within(client.send.Fetch.enable(params={"patterns": _PATTERNS}, session_id=session))
    await within(client.send.Network.enable(params={}, session_id=session))
    await within(client.send.Network.setBlockedURLs(params=_SOCKETS, session_id=session))
    await within(client.send.Target.setAutoAttach(
        params={"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, session_id=session))


async def install(client, gate: Gate) -> None:
    """The gate on every target of the session, now and later, once each (two gates on one tab
    would each judge its requests; seen on Steel, 2 Nov 2026); GateError when it cannot be."""
    from app.integrations.browser_cdp import within
    covered: Set[str] = set()

    def on_paused(event: Dict[str, Any], session: Optional[str] = None) -> None:
        request = event.get("request") or {}
        rid = event.get("requestId")
        verdict = gate.decide(request.get("method", ""), request.get("url", ""), event.get("resourceType", ""),
                              body=str(request.get("postData") or ""), session=str(session or ""),
                              frame=str(event.get("frameId") or ""), request=str(rid or ""))
        if verdict == HOLD:
            # Kept paused, not answered: his yes lets this very request go (`let_paused`).
            return
        if verdict == GO:
            reply = client.send.Fetch.continueRequest(params={"requestId": rid}, session_id=session)
        else:
            logger.info("[browser] a request was %s: %s", "stopped" if verdict == STOP else "blocked",
                        urlsplit(request.get("url", "")).hostname)
            reply = client.send.Fetch.failRequest(params={"requestId": rid, "errorReason": "BlockedByClient"},
                                                  session_id=session)
        # An answer the closing connection never sends is no error of the page's.
        asyncio.ensure_future(reply).add_done_callback(lambda done: done.cancelled() or done.exception())

    def on_socket(event: Dict[str, Any], session: Optional[str] = None) -> None:
        # Blocked before its handshake; one that was made anyway stops the fill.
        gate.blocked.append(("WEBSOCKET", str(event.get("url") or "")))
        gate.stop(SOCKET)

    def on_attached(event: Dict[str, Any], session: Optional[str] = None) -> None:
        new = event.get("sessionId")
        info = event.get("targetInfo") or {}
        target = info.get("targetId") or new
        if not new:
            return
        fresh = target not in covered
        covered.add(target)
        if info.get("type") == "page":
            gate.sessions.setdefault(target, new)

        async def hold_then_go():
            try:
                if fresh:
                    await _cover(client, gate, new, str(info.get("type") or ""))
            except _WIRE_ERRORS:
                # A target the gate is not on never runs: the fill stops.
                gate.stop("uncovered")
                return
            if event.get("waitingForDebugger"):
                await client.send.Runtime.runIfWaitingForDebugger(session_id=new)
        asyncio.ensure_future(hold_then_go())

    try:
        client.register.Fetch.requestPaused(on_paused)
        client.register.Network.webSocketCreated(on_socket)
        client.register.Target.attachedToTarget(on_attached)
        await within(client.send.Target.setAutoAttach(
            params={"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}))
        targets = (await within(client.send.Target.getTargets())).get("targetInfos") or []
        for t in targets:
            if t.get("type") != "page" or t["targetId"] in covered:
                continue
            covered.add(t["targetId"])
            session = (await within(client.send.Target.attachToTarget(
                params={"targetId": t["targetId"], "flatten": True})))["sessionId"]
            gate.sessions[t["targetId"]] = session
            await _cover(client, gate, session)
    except _WIRE_ERRORS as exc:  # whatever stops the gate stops the fill
        raise GateError(f"the gate could not be put on: {type(exc).__name__}") from exc
