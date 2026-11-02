"""The browser's gate and live view on a real Steel session, against a public form page.

    ~/sandy_app_venv/bin/python scripts/steel_live_check.py            # gate, header, live view
    ~/sandy_app_venv/bin/python scripts/steel_live_check.py --fill     # and a whole fill, real model

Needs `STEEL_API_KEY` in `.env` (and the chat model's settings for `--fill`). It costs a few cents
of Steel time and, with `--fill`, a few model calls. It prints what each check found and never
the key or an address that carries it. Every session it opens is released.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))

FORM = "https://httpbin.org/forms/post"
FILL_JS = """(() => { const f = document.forms[0];
  f.custname.value = "Sandy Test"; f.custtel.value = "000"; f.custemail.value = "test@example.com";
  return true; })()"""


def report(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


async def header_auth(session_id: str) -> bool:
    """Whether Steel takes the key in a header on the connect address (so it is never in a URL)."""
    from cdp_use.client import CDPClient

    from app import config
    client = CDPClient(f"wss://connect.steel.dev?sessionId={session_id}",
                       additional_headers={"steel-api-key": config.STEEL_API_KEY})
    try:
        await asyncio.wait_for(client.start(), 20)
        targets = await asyncio.wait_for(client.send.Target.getTargets(), 20)
        return bool(targets.get("targetInfos") is not None)
    except Exception as exc:  # noqa: BLE001 — a probe: any failure means no
        print(f"      header connect refused: {type(exc).__name__}")
        return False
    finally:
        try:
            await client.stop()
        except Exception:  # noqa: BLE001
            pass


CLICK_JS = "(() => { document.querySelector('form button').click(); return true; })()"
ANSWERED_JS = "document.body.innerText.includes('Sandy Test') && location.pathname === '/post'"


async def gate_checks(session_id: str) -> list:
    from app.brain import browser_gate
    from app.integrations import browser_cdp, steel_client
    results = []
    client = await browser_cdp.connect(steel_client.connect_url(session_id))
    try:
        gate = browser_gate.Gate("httpbin.org")
        await browser_gate.install(client, gate)
        tab = await browser_cdp.first_page(client)
        await browser_cdp.goto(client, tab, FORM)
        results.append(report("the form page opens behind the gate",
                              "forms/post" in await browser_cdp.where(client, tab)))
        await browser_cdp.evaluate(client, tab, FILL_JS)

        # 1. A script that submits the form by itself, with nothing clicked: blocked, never answered.
        await browser_cdp.evaluate(client, tab, "document.forms[0].submit(); true")
        await asyncio.sleep(3)
        answered = await browser_cdp.evaluate(client, tab, ANSWERED_JS)
        results.append(report("a script's form submit does not leave",
                              not answered and not gate.sent and gate.held is None and len(gate.blocked) >= 1,
                              f"blocked {len(gate.blocked)}"))

        # 2. A script's fetch POST: blocked, the page's promise fails.
        await browser_cdp.goto(client, tab, FORM)
        fetched = await browser_cdp.evaluate(client, tab, "fetch('/post', {method: 'POST', body: 'x=1'})"
                                             ".then(() => 'sent').catch(() => 'blocked')")
        results.append(report("a script's fetch POST does not leave", fetched == "blocked" and not gate.sent,
                              str(fetched)))

        # 3. The send button clicked, as the agent does: held with its body, never answered.
        await browser_cdp.evaluate(client, tab, FILL_JS)
        gate.acted("click")
        await browser_cdp.evaluate(client, tab, CLICK_JS)
        await asyncio.sleep(3)
        answered = await browser_cdp.evaluate(client, tab, ANSWERED_JS)
        held = dict(gate.held or {})
        results.append(report("a click on send is held for his yes, its body kept",
                              bool(held) and not gate.sent and not answered and "Sandy+Test" in held.get("body", ""),
                              f"{held.get('method')} {held.get('content_type')}"))
    finally:
        await client.stop()

    # 4. His yes, as `browser_job._send` does it: the held send itself, once.
    client = await browser_cdp.connect(steel_client.connect_url(session_id))
    try:
        gate = browser_gate.Gate("httpbin.org")
        await browser_gate.install(client, gate)
        from app.features.browser_job import _resend_js
        gate.replay(held)
        tab = await browser_cdp.first_page(client)
        await browser_cdp.goto(client, tab, FORM)
        await browser_cdp.evaluate(client, tab, _resend_js(held))
        await asyncio.sleep(1)
        await browser_cdp.settle(client, tab, 15)
        answered = await browser_cdp.evaluate(client, tab, ANSWERED_JS)
        results.append(report("with his yes, the held send goes once and the page answers",
                              len(gate.sent) == 1 and bool(answered), f"sent {len(gate.sent)}"))

        # 5. Another send after it: held again, not sent.
        await browser_cdp.goto(client, tab, FORM)
        await browser_cdp.evaluate(client, tab, FILL_JS)
        gate.acted("click")
        await browser_cdp.evaluate(client, tab, CLICK_JS)
        await asyncio.sleep(3)
        answered = await browser_cdp.evaluate(client, tab, ANSWERED_JS)
        results.append(report("a second send is not let through", len(gate.sent) == 1 and not answered,
                              f"sent {len(gate.sent)}"))

        # 6. A send from a tab opened later: the gate is on it before it loads.
        before = {t["targetId"] for t in (await client.send.Target.getTargets()).get("targetInfos") or []}
        await browser_cdp.evaluate(client, tab, "window.open('" + FORM + "', '_blank'); true")
        await asyncio.sleep(5)
        new = [t for t in (await client.send.Target.getTargets()).get("targetInfos") or []
               if t.get("type") == "page" and t["targetId"] not in before]
        if new:
            other = (await client.send.Target.attachToTarget(
                params={"targetId": new[0]["targetId"], "flatten": True}))["sessionId"]
            await browser_cdp.settle(client, other, 15)
            await browser_cdp.evaluate(client, other, FILL_JS)
            await browser_cdp.evaluate(client, other, "document.forms[0].submit(); true")
            await asyncio.sleep(3)
            answered = await browser_cdp.evaluate(client, other, ANSWERED_JS)
            results.append(report("a new tab's send is blocked too", len(gate.sent) == 1 and not answered,
                                  f"blocked {len(gate.blocked)}"))
        else:
            results.append(report("a new tab's send is blocked too", False, "no new tab opened"))
    finally:
        await client.stop()
    return results


def live_view(debug_url: str) -> bool:
    import requests
    if not debug_url:
        return report("the live view opens", False, "Steel gave no view")
    joiner = "&" if "?" in debug_url else "?"
    resp = requests.get(f"{debug_url}{joiner}interactive=false&showControls=false", timeout=20)
    return report("the live view opens", resp.status_code == 200 and "html" in resp.headers.get("content-type", ""),
                  f"HTTP {resp.status_code}")


def whole_fill() -> bool:
    """A whole fill through `page_fill` on the real model and Steel: held, then sent on his yes."""
    import os

    import mongomock

    from app import db as appdb
    from app.blocks import init_blocks
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    from app.features import browser_job, browser_sites
    from app.utils.user_profiles import active_user_profile_context

    os.environ["SANDY_FLAGS"] = json.dumps({"browser": ["live"]})
    d = mongomock.MongoClient().db
    appdb.configure(d)
    init_blocks(d)
    d["sandy_users"].insert_one({"_id": "live"})
    who = {"chat_id": "live", "relation": "user", "permissions": "all"}
    with active_user_profile_context(who):
        browser_sites.set_level("httpbin.org", browser_sites.SUBMIT)
        began = time.monotonic()
        asked = tools.execute("page_fill", {"url": FORM, "goal": "order a small pizza for pickup",
                                            "details": "Name: Sandy Test, phone: 000, email: test@example.com"},
                              TurnCtx(user_id="live", thread_id="t1"))
        print(f"      fill took {time.monotonic() - began:.0f}s: {json.dumps({k: asked.get(k) for k in ('ok', 'needs_confirmation')})}")
        if not asked.get("needs_confirmation"):
            print(f"      answer: {asked.get('reply') or asked.get('error')}")
            return report("a whole fill is held for his yes", False)
        report("a whole fill is held for his yes", True, asked["summary"][:120])
        ctx = TurnCtx(user_id="live", thread_id="t1")
        ctx.confirmed, ctx.held_ids = True, asked["ids"]
        sent = tools.execute("page_fill", {}, ctx)
        row = browser_job.get(asked["ids"][0]) or {}
        return report("his yes sends it once", sent.get("ok") is True and row.get("status") == browser_job.DONE,
                      (sent.get("reply") or "")[:120])


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--fill", action="store_true")
    args = parser.parse_args()

    from app.bootstrap import configure_logging
    from app.integrations import steel_client
    configure_logging("WARNING")
    if not steel_client.configured():
        print("no STEEL_API_KEY")
        return 2
    results = []
    session = steel_client.create_session()
    began = time.monotonic()
    try:
        # A finding, not a check: with no header, the key stays in the address and the log hides it.
        print(f"INFO  Steel takes the key in a header: {'yes' if asyncio.run(header_auth(session['id'])) else 'no'}")
        results += asyncio.run(gate_checks(session["id"]))
        results.append(live_view(session["debug_url"]))
    finally:
        steel_client.release(session["id"], time.monotonic() - began)
    if args.fill:
        results.append(whole_fill())
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
