"""Each site Sandy may open, for one account: what she may do there, and his sign-in to it.

`sandy_browser_sites`, one row per site under its user (`scoped`):

  {site, level, session, session_at, updated_at}

`level` is his alone to set, from the app's «Sites» screen: `set_level` takes his own signed-in
session (`Hand`, made by `PATCH /api/browser/sites/<site>` from its claims, the one caller), and
refuses while any tool runs (`ctx.IN_TOOL`), so no tool, the call, a task or a fill ever changes
one. `read` (the default: she reads, nothing else), `fill` (she fills a form
and never sends it, whatever he answers) or `submit` (she sends, and only on his yes). `session`
is what the phone sent after he signed in by hand there (`clean_state`: that site's cookies and
its storage, the known fields only, nothing named like a password), sealed with a key of its own
for that account and that site (HKDF from `SANDY_LTM_KEY`), so a row copied to another site or
account opens nothing. Without the server's key nothing is kept. «طلّعها» (`sign_out`) forgets
the sign-in and keeps the level. Erased with the account and with a reset.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from pymongo.errors import PyMongoError

from app.db import get_db
from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

COLLECTION = "sandy_browser_sites"
READ, FILL, SUBMIT = "read", "fill", "submit"
LEVELS = (READ, FILL, SUBMIT)
MAX_COOKIES = 300
MAX_VALUE = 4096
MAX_BYTES = 300_000
_COOKIE_FIELDS = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
_STATE_FIELDS = {"cookies", "storage"}
# A stored key that looks like a password is never kept, whatever the site put there.
_PASSWORD = re.compile(r"pass(word|code|wd)?|pwd", re.I)


def init_browser_sites(mongo_db) -> None:
    if mongo_db is None:
        return
    try:
        mongo_db[COLLECTION].create_index([("user_id", 1), ("site", 1)], unique=True, background=True)
    except PyMongoError as exc:
        logger.warning("[browser] sites index skipped: %s", exc)


def site_of(url_or_host: str) -> str:
    """The site a link or a name belongs to: its host, lowercase, without «www.»."""
    raw = str(url_or_host or "").strip().lower()
    host = urlsplit(raw if "://" in raw else f"https://{raw}").hostname or ""
    return host.rstrip(".").removeprefix("www.")


def _coll():
    return scoped(get_db(), COLLECTION, bump=False)


def _row(site: str) -> Dict[str, Any]:
    coll = _coll()
    if coll is None or not site:
        return {}
    try:
        return coll.find_one({"site": site}) or {}
    except PyMongoError:
        logger.warning("[browser] could not read site %s", site, exc_info=True)
        return {}


def level(site: str) -> str:
    found = _row(site_of(site)).get("level")
    return found if found in LEVELS else READ


def _write(site: str, *, put: Optional[Dict[str, Any]] = None,
           drop: Optional[Dict[str, Any]] = None) -> bool:
    """One change of the site's row, made when missing (read only until he says otherwise)."""
    coll = _coll()
    if coll is None or not site:
        return False
    put = dict(put or {})
    update: Dict[str, Any] = {"$set": {**put, "updated_at": datetime.now(timezone.utc)},
                              "$setOnInsert": {"site": site, **({} if "level" in put else {"level": READ})}}
    if drop:
        update["$unset"] = drop
    try:
        coll.update_one({"site": site}, update, upsert=True)
        return True
    except PyMongoError:
        logger.warning("[browser] could not change site %s", site, exc_info=True)
        return False


_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")


def valid_site(site: str) -> bool:
    """A site's name as he types it: a public domain, never an address or a bare word."""
    try:
        name = site.encode("idna").decode("ascii") if site else ""
    except UnicodeError:
        return False
    labels = name.split(".")
    return (len(labels) >= 2 and len(name) <= 253 and all(_LABEL.fullmatch(p) for p in labels)
            and not labels[-1].isdigit() and len(labels[-1]) >= 2)


class Hand:
    """His own signed-in session, from the app's route: the only way a level is changed."""

    def __init__(self, claims: Dict[str, Any]):
        if claims.get("role") == "guest" or not claims.get("user_id"):
            raise PermissionError("a level is changed only from his own signed-in session")
        self.user_id = str(claims["user_id"])


def set_level(site: str, new: str, *, hand: Hand) -> bool:
    from app.brain.ctx import IN_TOOL
    from app.utils.user_profiles import current_user_id
    if not isinstance(hand, Hand) or hand.user_id != (current_user_id() or ""):
        raise PermissionError("a level is changed only from his own signed-in session")
    if IN_TOOL.get():
        raise PermissionError("a level is never changed while a tool runs")
    if new not in LEVELS:
        raise ValueError(f"level is one of {LEVELS}")
    return _write(site_of(site), put={"level": new})


# ── His sign-in, sealed ──

def _fernet(user_id: str, site: str):
    raw = os.getenv("SANDY_LTM_KEY", "").strip()
    if not raw or not user_id or not site:
        return None
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=f"sandy-browser|{user_id}|{site}".encode()).derive(raw.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _seal(state: Dict[str, Any], user_id: str, site: str) -> Optional[str]:
    f = _fernet(user_id, site)
    return f.encrypt(json.dumps(state).encode()).decode() if f else None


def _open(sealed: Any, user_id: str, site: str) -> Optional[Dict[str, Any]]:
    from cryptography.fernet import InvalidToken
    f = _fernet(user_id, site)
    if f is None or not isinstance(sealed, str):
        return None
    try:
        return json.loads(f.decrypt(sealed.encode()))
    except (InvalidToken, ValueError):
        return None


def _belongs(domain: str, site: str) -> bool:
    """A cookie's domain is the site, one of its subdomains, or a parent it sits under."""
    domain = domain.lstrip(".").lower()
    if "." not in domain:
        return False
    return domain == site or domain.endswith("." + site) or site.endswith("." + domain)


def clean_state(site: str, state: Any) -> Dict[str, Any]:
    """What the phone sent, kept only as this site's cookies and storage; ValueError for
    anything else."""
    if not isinstance(state, dict) or set(state) - _STATE_FIELDS:
        raise ValueError("a sign-in is cookies and storage only")
    if len(json.dumps(state, default=str)) > MAX_BYTES:
        raise ValueError("too big")
    cookies = state.get("cookies") or []
    if not isinstance(cookies, list) or len(cookies) > MAX_COOKIES:
        raise ValueError("cookies are a list")
    out_cookies: List[Dict[str, Any]] = []
    for c in cookies:
        if not isinstance(c, dict) or set(c) - _COOKIE_FIELDS or not c.get("name"):
            raise ValueError("a cookie has its known fields only")
        if not _belongs(str(c.get("domain") or site), site):
            raise ValueError("a cookie of another site")
        if any(isinstance(c.get(k), str) and len(c[k]) > MAX_VALUE for k in ("name", "value")):
            raise ValueError("a cookie too long")
        out_cookies.append({k: c[k] for k in _COOKIE_FIELDS if k in c})
    storage = state.get("storage") or {}
    if not isinstance(storage, dict):
        raise ValueError("storage is by origin")
    out_storage: Dict[str, Dict[str, str]] = {}
    for origin, items in storage.items():
        if not _belongs(urlsplit(str(origin)).hostname or "", site) or not isinstance(items, dict):
            raise ValueError("storage of another site")
        out_storage[str(origin)] = {str(k): str(v)[:MAX_VALUE] for k, v in items.items()
                                    if not _PASSWORD.search(str(k))}
    return {"cookies": out_cookies, "storage": out_storage}


def save_session(site: str, state: Any) -> bool:
    """His sign-in to ``site``, cleaned and sealed; False when it cannot be kept safely
    (no key, no tenant). ValueError when it is not a sign-in of this site."""
    from app.utils.user_profiles import current_user_id
    site = site_of(site)
    sealed = _seal(clean_state(site, state), current_user_id() or "", site)
    if sealed is None:
        logger.warning("[browser] a sign-in to %s was not kept: no key", site)
        return False
    return _write(site, put={"session": sealed, "session_at": datetime.now(timezone.utc)})


def session(site: str) -> Optional[Dict[str, Any]]:
    from app.utils.user_profiles import current_user_id
    site = site_of(site)
    return _open(_row(site).get("session"), current_user_id() or "", site)


def sign_out(site: str) -> bool:
    """«طلّعها»: the sign-in forgotten, the level kept, and every fill open on the site closed
    with its session (it holds the sign-in in its browser)."""
    from app.features import browser_job
    name = site_of(site)
    coll = _coll()
    if coll is not None:
        browser_job.stop_for(coll.tenant, name)
    return _write(name, drop={"session": "", "session_at": ""})


def _shown(row: Dict[str, Any]) -> Dict[str, Any]:
    at = row.get("session_at")
    return {"site": row.get("site", ""), "level": row.get("level") if row.get("level") in LEVELS else READ,
            "signed_in": bool(row.get("session")),
            "session_at": at.replace(tzinfo=at.tzinfo or timezone.utc).isoformat() if isinstance(at, datetime) else None}


def sites() -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    try:
        # His own sites: a handful, read whole (بلا .limit() would cut the screen's list).
        rows = list(coll.find({}).sort("site", 1).limit(500))
    except PyMongoError:
        logger.warning("[browser] could not list sites", exc_info=True)
        return []
    return [_shown(r) for r in rows]


def shown(site: str) -> Dict[str, Any]:
    site = site_of(site)
    return _shown(_row(site) or {"site": site})
