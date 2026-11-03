"""The network gate of a fill: a safety net under the action's own question
(`features/browser_job`, which stops before a click or an Enter that sends and asks him first).

It is our own connection to the session, apart from browser-use's (`install`): every target, the
tabs open now and every tab, frame and worker attached later (`Target.setAutoAttach` with
`waitForDebuggerOnStart` on the browser and on each target, so each one waits until the gate is
on it), has `Fetch.enable` on it, no websocket or peer connection in its scripts (`PAGE_GUARD_JS`,
before the page's own), websockets blocked (`Network.setBlockedURLs`) and watched
(`Network.webSocketCreated`), and every request stops at the gate first (`decide`):

  * the page's own site: a read goes; after his yes (`approve`) exactly one send goes, the first
    from the tab and frame he said yes to once the click is made, and the gate shuts behind it;
    a request right after a click or a key the agent made (`acted`) is held (`HOLD`): answered at
    once with nothing (204), so it never waits in the browser and the page stays as it was, and
    the fill asks him about it (`on_hold`), the action that made it kept (`action`) so his yes
    makes that same action again: any send, and once Sandy typed a value any read too (a link
    with its query, a script's fetch), what a page loads aside; any other send is failed and
    logged;
  * another site: what a page loads goes (a script, a style, a font, an image, media, by GET);
    anything that sends (a fetch, a beacon, a form, a frame, any method but GET) is failed and
    logged;
  * any site but the page's own: a request whose address or body carries a value Sandy typed on
    the page (`typed`) is failed and stops the fill (`LEAK`), a GET for an image too.

A stop (`breach`) is told to the fill at once (`on_breach`), which closes the session and tells
him. A gate that cannot be put on (`GateError`) means no fill at all, and a gate whose connection
drops (`CUT`: the browser then asks no one about any request) stops the fill at once.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import functools
import ipaddress
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote_plus, urlsplit

logger = logging.getLogger(__name__)

GO, BLOCK, STOP, HOLD = "go", "block", "stop", "hold"
LEAK, SOCKET, CUT = "leak", "socket", "cut"
READS = ("GET", "HEAD", "OPTIONS")
# What a page loads from anywhere: never a send.
LOADS = ("Script", "Stylesheet", "Font", "Image", "Media")
# What follows these on the page's own site is held for him: a click, an Enter or any other key.
SENDING = ("click", "enter", "keys")
# What a click or a key made comes this soon after it; a request later is not its.
ACTED_S = 10
# A typed value shorter than this is too common to tell a leak by («1», «ok»).
MIN_TYPED = 3
# A value is watched word by word too, each word this long or more («Nabeel» of «Nabeel Alsultan»;
# never «Al» or «Lee», which any page carries).
MIN_WORD = 5
# What could be a value encoded in a request: base64 (and its web form) and hex.
_B64 = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
_HEX = re.compile(r"(?:[0-9a-fA-F]{2}){4,}")
_NO_NETWORK = ("data:", "blob:", "about:")
_PATTERNS = [{"urlPattern": "*", "requestStage": "Request"}]
_SOCKETS = {"urls": ["ws://*", "wss://*"],
            "urlPatterns": [{"urlPattern": "ws://*:*/*", "block": True}, {"urlPattern": "wss://*:*/*", "block": True}]}
# Run in every page, frame and worker before its own scripts: no websocket, no peer connection
# (each a way out the network gate never sees: tried on Steel, 2 Nov 2026, a blocked websocket
# still opened), and in a page no hint to open a name or a connection to another host
# (dns-prefetch, preconnect: they reach the network with no request the gate is asked about).
PAGE_GUARD_JS = r"""(() => { const no = function () { throw new DOMException("blocked", "SecurityError"); };
  for (const name of ["WebSocket", "WebTransport", "RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel"]) {
    try { Object.defineProperty(globalThis, name, {value: no, writable: false, configurable: false}); } catch (e) {} }
  if (typeof Element === "undefined" || typeof document === "undefined") return;
  const HINT = /(^|\s)(dns-prefetch|preconnect)(\s|$)/i;
  const away = (href) => { try { return new URL(href || "", location.href).hostname !== location.hostname; }
    catch (e) { return true; } };
  const P = (o, k) => Object.getOwnPropertyDescriptor(o, k);
  const getAttr = Element.prototype.getAttribute, setAttr = Element.prototype.setAttribute,
        dropAttr = Element.prototype.removeAttribute;
  const isLink = (el) => !!el && el.nodeType === 1 && el.localName === "link";
  // Whether a link with this rel and this href would be a hint to another host.
  const foreign = (rel, href) => HINT.test(rel || "") && away(href);
  const tame = (node) => {   // a node about to go in: its hints to other hosts lose their rel
    if (!node || typeof node !== "object") return node;
    const all = isLink(node) ? [node] : [];
    if (node.querySelectorAll) all.push(...node.querySelectorAll("link"));
    for (const l of all) if (foreign(getAttr.call(l, "rel"), getAttr.call(l, "href"))) dropAttr.call(l, "rel");
    return node; };
  const inert = (html) => { const t = document.createElement("template"); innerSet.call(t, String(html));
    tame(t.content); return innerGet.call(t); };
  const inner = P(Element.prototype, "innerHTML"), innerSet = inner.set, innerGet = inner.get;
  const wrapArgs = (proto, names) => { for (const n of names) { const f = proto[n]; if (!f) continue;
    Object.defineProperty(proto, n, {value: function (...a) { return f.apply(this, a.map(tame)); }, configurable: false}); } };
  wrapArgs(Node.prototype, ["appendChild", "insertBefore", "replaceChild"]);
  wrapArgs(Element.prototype, ["append", "prepend", "before", "after", "replaceWith", "replaceChildren",
    "insertAdjacentElement"]);
  wrapArgs(DocumentFragment.prototype, ["append", "prepend", "replaceChildren"]);
  wrapArgs(Document.prototype, ["append", "prepend", "replaceChildren"]);
  const wrapHtml = (proto, key) => { const d = P(proto, key); if (!d || !d.set) return;
    Object.defineProperty(proto, key, {get: d.get, set: function (v) { d.set.call(this, inert(v)); }, configurable: false}); };
  wrapHtml(Element.prototype, "innerHTML"); wrapHtml(Element.prototype, "outerHTML");
  if (typeof ShadowRoot !== "undefined") wrapHtml(ShadowRoot.prototype, "innerHTML");
  const adj = Element.prototype.insertAdjacentHTML;
  Object.defineProperty(Element.prototype, "insertAdjacentHTML", {value: function (where, html) {
    return adj.call(this, where, inert(html)); }, configurable: false});
  for (const n of ["write", "writeln"]) { const f = Document.prototype[n];
    Object.defineProperty(Document.prototype, n, {value: function (...a) { return f.apply(this, a.map(inert)); },
      configurable: false}); }
  for (const n of ["setHTMLUnsafe"]) for (const proto of [Element.prototype, typeof ShadowRoot !== "undefined" ? ShadowRoot.prototype : null]) {
    const f = proto && proto[n]; if (f) Object.defineProperty(proto, n, {value: function (html) { return f.call(this, inert(html)); },
      configurable: false}); }
  // A link's rel or href changed in place, by any of the ways a script can.
  const would = (el, name, value) => isLink(el) && ["rel", "href"].includes(String(name).toLowerCase())
    && foreign(String(name).toLowerCase() === "rel" ? value : getAttr.call(el, "rel"),
               String(name).toLowerCase() === "href" ? value : getAttr.call(el, "href"));
  Object.defineProperty(Element.prototype, "setAttribute", {value: function (name, value) {
    if (would(this, name, value)) return; return setAttr.call(this, name, value); }, configurable: false});
  const setNS = Element.prototype.setAttributeNS;
  Object.defineProperty(Element.prototype, "setAttributeNS", {value: function (ns, name, value) {
    if (would(this, String(name).split(":").pop(), value)) return; return setNS.call(this, ns, name, value); },
    configurable: false});
  for (const key of ["rel", "href"]) { const d = P(HTMLLinkElement.prototype, key);
    Object.defineProperty(HTMLLinkElement.prototype, key, {get: d.get, set: function (v) { this.setAttribute(key, v); },
      configurable: false}); }
  const val = P(Attr.prototype, "value");
  for (const key of ["value", "nodeValue", "textContent"]) { const d = P(Attr.prototype, key) || P(Node.prototype, key);
    if (!d || !d.set) continue;
    Object.defineProperty(Attr.prototype, key, {get: d.get, set: function (v) {
      if (would(this.ownerElement, this.name, v)) return; d.set.call(this, v); }, configurable: false}); }
  for (const n of ["setAttributeNode", "setAttributeNodeNS"]) { const f = Element.prototype[n];
    Object.defineProperty(Element.prototype, n, {value: function (attr) {
      if (would(this, attr.name, val.get.call(attr))) return null; return f.call(this, attr); }, configurable: false}); }
  const owners = new WeakMap(), attrs = P(Element.prototype, "attributes");
  Object.defineProperty(Element.prototype, "attributes", {get: function () { const m = attrs.get.call(this);
    owners.set(m, this); return m; }, configurable: false});
  for (const n of ["setNamedItem", "setNamedItemNS"]) { const f = NamedNodeMap.prototype[n];
    Object.defineProperty(NamedNodeMap.prototype, n, {value: function (attr) {
      if (would(owners.get(this), attr.name, val.get.call(attr))) return null; return f.call(this, attr); },
      configurable: false}); }
  // relList: each change tried on a copy that is in no page first.
  const lists = new WeakMap(), relList = P(HTMLLinkElement.prototype, "relList");
  Object.defineProperty(HTMLLinkElement.prototype, "relList", {get: function () { const l = relList.get.call(this);
    lists.set(l, this); return l; }, configurable: false});
  const DTL = DOMTokenList.prototype, value = P(DTL, "value");
  const tried = (list, change) => { const el = lists.get(list); if (!el) return false;
    const copy = document.createElement("link"); setAttr.call(copy, "rel", getAttr.call(el, "rel") || "");
    change(relList.get.call(copy)); return foreign(getAttr.call(copy, "rel"), getAttr.call(el, "href")); };
  for (const n of ["add", "toggle", "replace"]) { const f = DTL[n];
    Object.defineProperty(DTL, n, {value: function (...a) { if (tried(this, (c) => f.apply(c, a))) return false;
      return f.apply(this, a); }, configurable: false}); }
  Object.defineProperty(DTL, "value", {get: value.get, set: function (v) {
    if (tried(this, (c) => value.set.call(c, v))) return; value.set.call(this, v); }, configurable: false});
  const meta = () => { try { const m = document.createElement("meta"); setAttr.call(m, "http-equiv", "x-dns-prefetch-control");
    setAttr.call(m, "content", "off"); (document.head || document.documentElement).appendChild(m); } catch (e) {} };
  if (document.documentElement) meta(); else document.addEventListener("readystatechange", meta, {once: true});
})()"""
_FRAMES = ("page", "iframe")


def _readings(raw: str) -> str:
    """Every reading of a request's text a value could hide in, lowercase."""
    once = unquote_plus(raw)
    texts = [raw, once, unquote_plus(once)]
    decoded = []
    for text in texts:
        for token in {piece for found in _B64.findall(text) for piece in (found, *found.split("/")) if piece}:
            for alphabet in (None, b"-_"):
                try:
                    decoded.append(base64.b64decode(token + "=" * (-len(token) % 4), altchars=alphabet))
                except (binascii.Error, ValueError):
                    pass
        for token in _HEX.findall(text):
            decoded.append(bytes.fromhex(token))
    readings = texts + [d.decode("utf-8", "ignore") for d in decoded]
    return "\n".join(readings + [unquote_plus(r) for r in readings[3:]]).lower()


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
        self.acted_at = 0.0
        self.typed: Set[str] = set()
        # Whether Sandy typed on the page yet: from then on a read after a click is held too.
        self.wrote = False
        # A page he took over: what he sends to its own site goes (`browser_job._handing`).
        self.his = False
        # The agent's last action on an element ({kind, target, node}): what his yes makes again.
        self.action: Optional[Dict[str, Any]] = None
        # The one request he is asked about ({session, request, method, url, action}), answered
        # with nothing already, and who is told of it.
        self.asked: Optional[Dict[str, Any]] = None
        # What he filled, read before the agent's last click or key (a held page cannot be read).
        self.filled: List[Dict[str, Any]] = []
        self.on_hold: Optional[Callable[[Dict[str, Any]], None]] = None
        # The tab and frame whose one send his yes lets through, until it goes (`approve`).
        self.armed: Optional[Tuple[str, str]] = None
        self.breach: Optional[str] = None
        self.on_breach: Optional[Callable[[str], None]] = None
        self.blocked: List[Tuple[str, str]] = []
        self.sent: List[Tuple[str, str]] = []
        # Each page's own session on our connection, by its target (the real click is made there).
        self.sessions: Dict[str, str] = {}

    def acted(self, kind: str, text: str = "", *, target: str = "", node: Optional[int] = None) -> None:
        """What the model just did on the page: «click», «enter», «keys» or «type» (with what it
        typed), on the element ``node`` of the tab ``target`` when it is known."""
        self.last, self.acted_at = kind, time.monotonic()
        if node is not None:
            self.action = {"kind": kind, "target": str(target or ""), "node": node}
        if kind == "type":
            self.wrote = True
            self.watch(text)

    def watch(self, text: str) -> None:
        """A value of his that must never reach another site (what Sandy will type)."""
        whole = str(text or "").strip()
        if len(whole) >= MIN_TYPED:
            self.typed.add(whole)
        self.typed.update(word for word in whole.split() if len(word) >= MIN_WORD)

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
        """A request the agent's click or key made: held for him, the first one (answered with
        nothing, the action that made it kept); any after it while he is asked is blocked."""
        if self.asked is not None or not request:
            self.blocked.append((method, url))
            return BLOCK
        self.asked = {"session": str(session or ""), "request": str(request), "method": method, "url": url,
                      "action": self.action}
        logger.info("[browser] a request was held for him: %s", urlsplit(url).hostname)
        if self.on_hold is not None:
            self.on_hold(self.asked)
        return HOLD

    def _carries(self, url: str, body: str) -> bool:
        """Whether a request carries a value Sandy typed, as typed or encoded: escaped for a link
        (once or twice), in base64 or its web form, or in hex."""
        if not self.typed:
            return False
        seen = _readings(f"{url}\n{body}")
        return any(value.lower() in seen for value in self.typed)

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
            just = self.last in SENDING and time.monotonic() - self.acted_at < ACTED_S
            if just and not loads and (method not in READS or self.wrote):
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
            params={"source": PAGE_GUARD_JS, "runImmediately": True}, session_id=session))
    await within(client.send.Runtime.evaluate(params={"expression": PAGE_GUARD_JS}, session_id=session))
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
            # Never kept waiting in the browser (a page whose request waits is frozen, and the
            # request would go the moment our connection dropped): answered with nothing, it goes
            # nowhere and the page stays as it was; his yes makes the action that made it again.
            reply = client.send.Fetch.fulfillRequest(params={"requestId": rid, "responseCode": 204,
                                                             "responseHeaders": []}, session_id=session)
        elif verdict == GO:
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

    def on_cut(reading: "asyncio.Future") -> None:
        # Our connection's reader ended without our stopping it: the connection dropped.
        if not reading.cancelled():
            gate.stop(CUT)

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
        # cdp-use's reader of the connection (`PROVEN`): it ends once the connection drops.
        reading = client._message_handler_task
        if reading is None or reading.done():
            raise ConnectionError("the gate's connection is not open")
        reading.add_done_callback(on_cut)
    except _WIRE_ERRORS as exc:  # whatever stops the gate stops the fill
        raise GateError(f"the gate could not be put on: {type(exc).__name__}") from exc
