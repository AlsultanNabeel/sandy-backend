"""App auth: JWT issue/verify, route decorators, and login rate limiting.

``JWT_SECRET`` has no default: an empty secret would let anyone forge tokens.
Rate limits live in Mongo with an in-process fallback during a DB outage.
"""
from __future__ import annotations

import functools
import logging
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import jwt
from flask import jsonify, make_response, request
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

_JWT_ALGO = "HS256"
AUTH_TOKEN_HOURS = 24 * 7    # any signed-in user
GUEST_TOKEN_HOURS = 48
# A signed-in token this old comes back renewed (`RENEWED_HEADER`), so a session in use
# never reaches its end; one left unused for AUTH_TOKEN_HOURS does.
RENEW_AFTER_HOURS = 24
RENEWED_HEADER = "X-Sandy-Token"
_RATE_WINDOW = 900            # 15 minutes
_RATE_MAX = 5                 # max login attempts per window

# In-process fallback when Mongo is unavailable.
_ip_hits: dict[str, deque] = {}
_ip_hits_lock = threading.Lock()


def _memory_rate_check(ip: str, scope: str = "login") -> Tuple[bool, int]:
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    key = f"{scope}:{ip}"
    with _ip_hits_lock:
        dq = _ip_hits.setdefault(key, deque())
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= _RATE_MAX:
            return False, 0
        dq.append(now)
        return True, max(0, _RATE_MAX - len(dq))


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set; refusing to issue or verify tokens")
    return secret


def role_for_email(email: str) -> str:
    """``owner`` for addresses in SANDY_OWNER_EMAILS (comma-separated, case-insensitive), else ``user``."""
    from app.config import SANDY_OWNER_EMAILS

    wanted = {e.strip().lower() for e in SANDY_OWNER_EMAILS.split(",") if e.strip()}
    return "owner" if wanted and (email or "").strip().lower() in wanted else "user"


def make_token(role: str, user_id: Optional[str] = None, gen: int = 0) -> str:
    """``gen`` is the account's token generation (`users_store.token_generation`)."""
    hours = GUEST_TOKEN_HOURS if role == "guest" else AUTH_TOKEN_HOURS
    payload = {
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    if user_id:
        payload["user_id"] = str(user_id)
        payload["gen"] = int(gen)
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGO)


# A signed-in token is honoured only while its account exists on the same generation.
# The answer is kept a minute at most per account and forgotten at once when the account
# is deleted (`forget_generation`); a read that fails serves the last answer kept, and with
# none the request goes through, so a database hiccup does not sign everyone out.
GENERATION_TTL_S = 60
_generations: dict[str, Tuple[float, Optional[int]]] = {}
_generations_lock = threading.Lock()
_clock = time.monotonic


def account_generation(user_id: str) -> Optional[int]:
    """The account's generation, None when there is no account; raises
    `GenerationUnreadable` when it cannot be read and no answer is kept."""
    from app.features import users_store
    with _generations_lock:
        kept = _generations.get(user_id)
    if kept and _clock() - kept[0] < GENERATION_TTL_S:
        return kept[1]
    try:
        gen = users_store.token_generation(user_id)
    except users_store.GenerationUnreadable:
        if kept:
            return kept[1]
        raise
    with _generations_lock:
        _generations[user_id] = (_clock(), gen)
    return gen


def forget_generation(user_id: str) -> None:
    """The account changed (deleted): its next token is checked against the database."""
    with _generations_lock:
        _generations.pop(user_id, None)


def account_allows(claims: dict) -> bool:
    """False when a signed-in token's account is gone or moved to another generation."""
    user_id = claims.get("user_id")
    if claims.get("role") == "guest" or not user_id:
        return True
    from app.features.users_store import GenerationUnreadable
    try:
        gen = account_generation(str(user_id))
    except GenerationUnreadable:
        logger.warning("[auth] generation unreadable for %s; letting the request through", user_id)
        return True
    return gen is not None and gen == int(claims.get("gen") or 0)


def renewed_token(claims: dict) -> Optional[str]:
    """A new token for a signed-in account whose token is RENEW_AFTER_HOURS old, on the
    same generation. None for a guest or a fresh token; a revoked, orphaned or expired one
    never gets here (`require_auth` refused it)."""
    user_id = claims.get("user_id")
    if claims.get("role") == "guest" or not user_id:
        return None
    if time.time() - float(claims.get("iat") or 0) < RENEW_AFTER_HOURS * 3600:
        return None
    try:
        return make_token(str(claims.get("role")), user_id=str(user_id),
                          gen=int(claims.get("gen") or 0))
    except RuntimeError:
        return None


def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except RuntimeError:
        return None


def _claims_from_request() -> Optional[dict]:
    """Verified claims from the Authorization header, else a ``token`` field in the JSON body."""
    auth_header = request.headers.get("Authorization", "")
    token_str = auth_header.removeprefix("Bearer ").strip()
    if not token_str:
        body = request.get_json(silent=True) or {}
        token_str = (body.get("token") or "").strip()
    if not token_str:
        return None
    return verify_token(token_str)


def require_auth(view):
    """401 unless a valid token is present; passes the claims as ``claims=``. A token due
    for renewal gets its successor in the ``RENEWED_HEADER`` of the response."""

    @functools.wraps(view)
    def _wrapped(*args, **kwargs):
        claims = _claims_from_request()
        if not claims or not account_allows(claims):
            return jsonify({"error": "unauthorized"}), 401
        if claims.get("role") != "guest" and request.headers.get("X-Timezone"):
            # The phone says where it is on every call; kept only when it changed.
            from app.utils.time import note_zone
            note_zone(claims.get("user_id"), request.headers["X-Timezone"])
        response = view(*args, claims=claims, **kwargs)
        renewed = renewed_token(claims)
        if renewed is None:
            return response
        response = make_response(response)
        response.headers[RENEWED_HEADER] = renewed
        return response

    return _wrapped


def require_tenant(view):
    """Auth for a mutating endpoint: 401 without a token, 403 for guests, then runs in the caller's tenant context."""

    @functools.wraps(view)
    def _inner(*args, claims, **kwargs):
        if claims.get("role") == "guest":
            return jsonify({"error": "forbidden"}), 403
        from app.utils.user_profiles import (
            active_user_profile_context,
            build_user_profile,
        )
        with active_user_profile_context(build_user_profile(claims)):
            return view(*args, claims=claims, **kwargs)

    return require_auth(_inner)


# Login rate-limit state: sandy_auth, TTL-indexed on expire_at.
_AUTH_COLL = "sandy_auth"
_auth_index_ready = False


def _auth_coll():
    global _auth_index_ready
    try:
        from app.db import get_db
        mongo_db = get_db()
        if mongo_db is None:
            return None
        coll = mongo_db[_AUTH_COLL]
        if not _auth_index_ready:
            try:
                coll.create_index("expire_at", expireAfterSeconds=0, background=True)
            except Exception:
                logger.debug("ignoring non-critical error", exc_info=True)
            _auth_index_ready = True
        return coll
    except Exception:
        return None


# Email sign-in counts failures only, so signing in rightly never uses the limit up: per
# address, per (email, address), and per email alone with a higher ceiling, so neither a
# stranger's guesses keep the owner out nor a new address per guess guesses without end.
EMAIL_LOGIN_LIMITS = {"email_login": 20, "email_login_pair": 5, "email_login_acct": 20}


def _memory_failures(key: str, add: bool) -> int:
    now = time.monotonic()
    with _ip_hits_lock:
        dq = _ip_hits.setdefault(f"fail:{key}", deque())
        while dq and dq[0] <= now - _RATE_WINDOW:
            dq.popleft()
        if add:
            dq.append(now)
        return len(dq)


def _failures(key: str, add: bool) -> int:
    """Failures of ``key`` in the window, after adding one when ``add``."""
    coll = _auth_coll()
    if coll is None:
        logger.warning("[auth] Mongo unavailable; using in-memory failure count")
        return _memory_failures(key, add)
    try:
        if not add:
            return int((coll.find_one({"_id": f"fail:{key}"}) or {}).get("count", 0))
        from pymongo import ReturnDocument
        now = datetime.now(timezone.utc)
        doc = coll.find_one_and_update(
            {"_id": f"fail:{key}"},
            {"$inc": {"count": 1},
             "$setOnInsert": {"expire_at": now + timedelta(seconds=_RATE_WINDOW)}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int((doc or {}).get("count", 1))
    except PyMongoError as exc:
        logger.warning("[auth] Mongo unavailable; using in-memory failure count (%s)", exc)
        return _memory_failures(key, add)


def failures_over_limit(checks) -> bool:
    """True when any ``(key, scope)`` has used up its scope's failures in this window."""
    return any(_failures(f"{scope}:{key}", add=False) >= EMAIL_LOGIN_LIMITS[scope]
               for key, scope in checks)


def note_failures(checks) -> None:
    """One more failure on every ``(key, scope)``."""
    for key, scope in checks:
        _failures(f"{scope}:{key}", add=True)


def check_rate_limit(ip: str, scope: str = "login") -> Tuple[bool, int]:
    """(allowed, attempts_remaining); ``scope`` keeps limiters independent."""
    coll = _auth_coll()
    if coll is None:
        logger.warning(
            "[auth] Mongo unavailable; using in-memory rate limit fallback"
        )
        return _memory_rate_check(ip, scope)
    try:
        from pymongo import ReturnDocument
        now = datetime.now(timezone.utc)
        doc = coll.find_one_and_update(
            {"_id": f"rate:{scope}:{ip}"},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {"expire_at": now + timedelta(seconds=_RATE_WINDOW)},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        count = (doc or {}).get("count", 1)
        return count <= _RATE_MAX, max(0, _RATE_MAX - count)
    except Exception as exc:
        logger.warning(
            "[auth] Mongo unavailable; using in-memory rate limit fallback (%s)",
            exc,
        )
        return _memory_rate_check(ip, scope)


