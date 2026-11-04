"""Steel's cloud browser (steel.dev), for pages a plain request cannot read.

`scrape`, Steel's Browser Tools endpoint (`POST /v1/scrape`), opens a public page in a real
browser, lets its scripts run, and gives back the HTML, the links and, when asked, a screenshot.
Steel keeps that screenshot at a public link, so a page that needs a sign-in never asks for one.

`create_session` opens a browser of his own for a while (`POST /v1/sessions`): its id, the
address our code drives it by (`connect_url`, the key inside it, never logged) and the live view
Steel draws it in (`debug_url`, which has no protection of its own: it reaches only the job's
owner, `api/browser_api`). `release` closes it and bills its time on the trace (`steel_hour`);
`closed` asks whether it is; `live_sessions` lists the ones still open on our account.

`STEEL_API_KEY` names the account; without it nothing is sent and `configured` is false.
Each call is one `pricing.FEES["steel_tool"]` on the current trace. A failure raises
`SteelError`, whatever it was (no key, a timeout, Steel's 429 at twenty calls a minute).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from app import config
from app.features import trace_store

logger = logging.getLogger(__name__)

API = "https://api.steel.dev/v1"
TIMEOUT_S = 30
# A session is closed by Steel itself after this long, whatever happens to us.
SESSION_MS = 15 * 60 * 1000


class SteelError(RuntimeError):
    """Steel could not do what was asked."""


def configured() -> bool:
    return bool(config.STEEL_API_KEY)


def _post(path: str, body: Dict[str, Any], timeout: float = TIMEOUT_S) -> Dict[str, Any]:
    if not configured():
        raise SteelError("no Steel key")
    try:
        resp = requests.post(f"{API}{path}", json=body, timeout=timeout,
                             headers={"steel-api-key": config.STEEL_API_KEY})
    except requests.RequestException as exc:
        raise SteelError(f"Steel did not answer: {type(exc).__name__}") from exc
    if resp.status_code not in (200, 201):
        logger.warning("[steel] %s answered %s", path.strip("/").split("/")[0], resp.status_code)
        raise SteelError(f"Steel answered {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SteelError("Steel answered something that is not JSON") from exc


def connect_url(session_id: str) -> str:
    return f"wss://connect.steel.dev?apiKey={config.STEEL_API_KEY}&sessionId={session_id}"


def create_session() -> Dict[str, str]:
    """A browser of his own: ``{id, debug_url}``; Steel closes it after `SESSION_MS`."""
    data = _post("/sessions", {"timeout": SESSION_MS})
    if not data.get("id"):
        raise SteelError("Steel gave no session")
    return {"id": str(data["id"]), "debug_url": str(data.get("debugUrl") or "")}


def release(session_id: str, seconds: float = 0, timeout: float = TIMEOUT_S) -> bool:
    """The session closed, its time billed; True once Steel has it closed (a failure is logged).
    ``timeout`` for each call to Steel: short when the process is ending."""
    if seconds > 0:
        trace_store.note_fee("steel_hour", seconds / 3600)
    try:
        _post(f"/sessions/{session_id}/release", {}, timeout=timeout)
        return True
    except SteelError as exc:
        if closed(session_id, timeout=timeout):
            return True
        logger.warning("[steel] a session was not released: %s", exc)
        return False


def live_sessions() -> List[Dict[str, str]]:
    """The sessions still open on our account: ``[{id, created_at}]``; SteelError when Steel
    cannot be asked."""
    if not configured():
        return []
    try:
        resp = requests.get(f"{API}/sessions", params={"status": "live"}, timeout=TIMEOUT_S,
                            headers={"steel-api-key": config.STEEL_API_KEY})
        data = resp.json() if resp.ok else None
    except (requests.RequestException, ValueError) as exc:
        raise SteelError(f"Steel did not list its sessions: {type(exc).__name__}") from exc
    if data is None:
        raise SteelError(f"Steel answered {resp.status_code}")
    rows = data.get("sessions") if isinstance(data, dict) else data
    return [{"id": str(s["id"]), "created_at": str(s.get("createdAt") or "")}
            for s in rows or [] if isinstance(s, dict) and s.get("id")]


def closed(session_id: str, timeout: float = TIMEOUT_S) -> bool:
    """Whether Steel says the session is closed; False when it cannot be told."""
    if not configured() or not session_id:
        return False
    try:
        resp = requests.get(f"{API}/sessions/{session_id}", timeout=timeout,
                            headers={"steel-api-key": config.STEEL_API_KEY})
        return resp.ok and str((resp.json() or {}).get("status") or "") == "released"
    except (requests.RequestException, ValueError, AttributeError):
        return False


def scrape(url: str, *, screenshot: bool = False) -> Dict[str, Any]:
    """The page as Steel's browser saw it: ``{html, title, links, screenshot, status}`` (the
    screenshot's link, or ""; the site's HTTP status, 0 when Steel did not say)."""
    body: Dict[str, Any] = {"url": url, "format": ["html"]}
    if screenshot:
        body["screenshot"] = True
    try:
        data = _post("/scrape", body)
    finally:
        if configured():
            trace_store.note_fee("steel_tool")
    content = data.get("content") or {}
    meta = data.get("metadata") or {}
    shot = data.get("screenshot") or {}
    return {"html": str(content.get("html") or ""), "title": str(meta.get("title") or ""),
            "links": [{"title": str(link.get("text") or "").strip(), "url": str(link.get("url") or "")}
                      for link in data.get("links") or [] if isinstance(link, dict)],
            "screenshot": str(shot.get("url") or "") if isinstance(shot, dict) else "",
            "status": int(meta.get("statusCode") or 0) if str(meta.get("statusCode") or "0").isdigit() else 0}
