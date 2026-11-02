"""The server never carries or starts a browser of its own: every page a fill or a signed-in read
opens is in a Steel session (measured 2 Nov 2026: browser-use adds about 44 MB to the compressed
slug, the whole near 130 MB of Heroku's 500, and no browser binary)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_BROWSERS = re.compile(r"^(playwright|pyppeteer|selenium|undetected-chromedriver|chromedriver)", re.I)


def test_no_browser_is_a_requirement():
    lines = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    assert not [line for line in lines if _BROWSERS.match(line)]


def test_the_fills_agent_is_only_ever_given_steels_session():
    source = (ROOT / "cloud/app/features/browser_job.py").read_text()
    sessions = re.findall(r"BrowserSession\(([^)]*)\)", source)
    assert sessions and all("cdp_url=steel_client.connect_url" in s for s in sessions)
