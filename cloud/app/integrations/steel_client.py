"""Steel's cloud browser (steel.dev), for pages a plain request cannot read.

One call for now: `scrape`, Steel's Browser Tools endpoint (`POST /v1/scrape`), which opens the
page in a real browser, lets its scripts run, and gives back the HTML, the links and, when
asked, a screenshot. Steel keeps that screenshot at a public link, so a page that needs a
sign-in never asks for one (the second session's pages go through a session of their own).

`STEEL_API_KEY` names the account; without it nothing is sent and `configured` is false.
Each call is one `pricing.FEES["steel_tool"]` on the current trace. A failure raises
`SteelError`, whatever it was (no key, a timeout, Steel's 429 at twenty calls a minute).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import requests

from app import config
from app.features import trace_store

logger = logging.getLogger(__name__)

API = "https://api.steel.dev/v1"
TIMEOUT_S = 30


class SteelError(RuntimeError):
    """Steel could not read the page."""


def configured() -> bool:
    return bool(config.STEEL_API_KEY)


def scrape(url: str, *, screenshot: bool = False) -> Dict[str, Any]:
    """The page as Steel's browser saw it: ``{html, title, links, screenshot}`` (the
    screenshot's link, or "")."""
    if not configured():
        raise SteelError("no Steel key")
    body: Dict[str, Any] = {"url": url, "format": ["html"]}
    if screenshot:
        body["screenshot"] = True
    try:
        resp = requests.post(f"{API}/scrape", json=body, timeout=TIMEOUT_S,
                             headers={"steel-api-key": config.STEEL_API_KEY})
    except requests.RequestException as exc:
        raise SteelError(f"Steel did not answer: {type(exc).__name__}") from exc
    finally:
        trace_store.note_fee("steel_tool")
    if resp.status_code != 200:
        logger.warning("[steel] scrape answered %s", resp.status_code)
        raise SteelError(f"Steel answered {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise SteelError("Steel answered something that is not JSON") from exc
    content = data.get("content") or {}
    meta = data.get("metadata") or {}
    shot = data.get("screenshot") or {}
    return {"html": str(content.get("html") or ""), "title": str(meta.get("title") or ""),
            "links": [{"title": str(link.get("text") or "").strip(), "url": str(link.get("url") or "")}
                      for link in data.get("links") or [] if isinstance(link, dict)],
            "screenshot": str(shot.get("url") or "") if isinstance(shot, dict) else ""}
