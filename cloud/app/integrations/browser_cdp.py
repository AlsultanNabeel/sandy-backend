"""Driving a live browser (a Steel session) over the DevTools protocol, with `cdp-use`.

The few things our own code does in a session, apart from the fill's model (`features/browser_job`):
open the page, put his sign-in in before it (cookies with `Storage.setCookies`, each origin's
storage once the origin is open), read the page, run a line of script, click an element by its
path. Every call is awaited inside one `asyncio.run`, on the thread that asked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LOAD_S = 20
_SAME_SITE = {"strict": "Strict", "lax": "Lax", "none": "None"}


async def connect(url: str):
    from cdp_use.client import CDPClient
    client = CDPClient(url)
    await client.start()
    return client


async def first_page(client) -> str:
    """The session id of the browser's first page (one is opened when there is none)."""
    targets = (await client.send.Target.getTargets()).get("targetInfos") or []
    page = next((t for t in targets if t.get("type") == "page"), None)
    target = page["targetId"] if page else (await client.send.Target.createTarget(
        params={"url": "about:blank"}))["targetId"]
    return (await client.send.Target.attachToTarget(params={"targetId": target, "flatten": True}))["sessionId"]


async def evaluate(client, session: str, expression: str) -> Any:
    found = await client.send.Runtime.evaluate(
        params={"expression": expression, "returnByValue": True, "awaitPromise": True}, session_id=session)
    return (found.get("result") or {}).get("value")


async def goto(client, session: str, url: str, wait_s: float = LOAD_S) -> None:
    """Open ``url`` and wait for it to load (`wait_s` at most; a slow page is read as it is)."""
    await client.send.Page.navigate(params={"url": url}, session_id=session)
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
        await client.send.Storage.setCookies(params={"cookies": cookies})
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


async def click(client, session: str, xpath: str) -> bool:
    """Click the element at ``xpath``; False when it is not there."""
    return bool(await evaluate(client, session, "(() => { const el = document.evaluate(" + json.dumps(xpath)
                               + ", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null)"
                               ".singleNodeValue; if (!el) return false; el.click(); return true; })()"))


async def click_at(client, session: str, x: float, y: float) -> None:
    for kind in ("mousePressed", "mouseReleased"):
        await client.send.Input.dispatchMouseEvent(
            params={"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1}, session_id=session)


async def press_enter(client, session: str) -> None:
    for kind in ("keyDown", "keyUp"):
        await client.send.Input.dispatchKeyEvent(
            params={"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}, session_id=session)
