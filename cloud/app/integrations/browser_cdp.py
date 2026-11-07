"""Driving a live browser (a Steel session) over the DevTools protocol, with `cdp-use`.

The few things our own code does in a session, apart from the fill's model (`features/browser_job`):
open the page, put his sign-in in before it (cookies with `Storage.setCookies`, each origin's
storage once the origin is open), read the page, run a line of script. Every call is awaited inside one `asyncio.run`, on the thread that asked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LOAD_S = 20
# One call to the browser, at most: a call that never answers never holds a worker.
CALL_S = 20
# A connection whose opening handshake times out is tried again, this many times in all.
CONNECT_TRIES = 3
_SAME_SITE = {"strict": "Strict", "lax": "Lax", "none": "None"}


async def within(call, seconds: float = CALL_S):
    """``call`` awaited `CALL_S` at most."""
    return await asyncio.wait_for(call, seconds)


# A connection closing is given this long: one that never closes never holds up what ends it.
STOP_S = 5


async def closing(stop, seconds: float = STOP_S, what: str = "connection") -> None:
    """``stop`` (a close) awaited ``seconds`` at most; one that does not close in time is left and
    logged, so a fill or a read always ends and leaves its trace."""
    try:
        await asyncio.wait_for(stop, seconds)
    except asyncio.TimeoutError:
        logger.warning("[browser] a %s did not close in %ss; left", what, seconds)


async def connect(url: str):
    """A connection to ``url``, whose key no log ever shows (cdp-use logs the address)."""
    from cdp_use.client import CDPClient

    from app.bootstrap import install_redaction
    install_redaction()
    for attempt in range(1, CONNECT_TRIES + 1):
        client = CDPClient(url)
        try:
            await within(client.start())
            return client
        except BaseException as exc:
            # A failed attempt is closed, never left half open.
            await _close(client)
            if attempt == CONNECT_TRIES or not isinstance(exc, (OSError, asyncio.TimeoutError)):
                raise
            # Steel's handshake sometimes outlasts the library's own ten seconds (seen 3 Nov 2026).
            logger.info("[browser] the connection was slow to open; once more")
    raise ConnectionError("no connection was tried")


async def _close(client) -> None:
    try:
        await within(client.stop(), 5)
    except (OSError, RuntimeError, asyncio.TimeoutError) as exc:
        logger.info("[browser] a failed connection did not close cleanly: %s", type(exc).__name__)


async def first_page(client) -> str:
    """The session id of the browser's first page (one is opened when there is none)."""
    targets = (await within(client.send.Target.getTargets())).get("targetInfos") or []
    page = next((t for t in targets if t.get("type") == "page"), None)
    target = page["targetId"] if page else (await within(client.send.Target.createTarget(
        params={"url": "about:blank"})))["targetId"]
    return (await within(client.send.Target.attachToTarget(
        params={"targetId": target, "flatten": True})))["sessionId"]


async def evaluate(client, session: str, expression: str) -> Any:
    found = await within(client.send.Runtime.evaluate(
        params={"expression": expression, "returnByValue": True, "awaitPromise": True}, session_id=session))
    return (found.get("result") or {}).get("value")


async def goto(client, session: str, url: str, wait_s: float = LOAD_S) -> None:
    """Open ``url`` and wait for it to load (`wait_s` at most; a slow page is read as it is)."""
    await within(client.send.Page.navigate(params={"url": url}, session_id=session))
    await settle(client, session, wait_s)


async def settle(client, session: str, wait_s: float = LOAD_S) -> None:
    """Wait for the page now opening to load (`wait_s` at most)."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        await asyncio.sleep(0.3)
        if await evaluate(client, session, "document.readyState") == "complete":
            return
    logger.info("[browser] a page was still loading after %ss", wait_s)


def _cookie(c: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: c[k] for k in ("name", "value", "domain", "path", "secure", "httpOnly") if k in c}
    if c.get("expires"):
        out["expires"] = float(c["expires"])
    same = _SAME_SITE.get(str(c.get("sameSite") or "").lower())
    if same:
        out["sameSite"] = same
    return out


async def apply_state(client, session: str, state: Optional[Dict[str, Any]]) -> None:
    """His sign-in, before any page of the site opens."""
    if not state:
        return
    cookies: List[Dict[str, Any]] = [_cookie(c) for c in state.get("cookies") or []]
    if cookies:
        await within(client.send.Storage.setCookies(params={"cookies": cookies}))
    for origin, items in (state.get("storage") or {}).items():
        if not items:
            continue
        await goto(client, session, origin)
        await evaluate(client, session, "(() => { const items = " + json.dumps(items)
                       + "; for (const k in items) localStorage.setItem(k, items[k]); return true; })()")


async def html(client, session: str) -> str:
    return str(await evaluate(client, session, "document.documentElement.outerHTML") or "")


async def where(client, session: str) -> str:
    return str(await evaluate(client, session, "location.href") or "")
