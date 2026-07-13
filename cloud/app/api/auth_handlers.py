"""Sandy web auth: JWT access control with a Telegram approval flow."""
from __future__ import annotations

import functools
import hashlib
import hmac
import logging
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import jwt  # PyJWT
from flask import jsonify, request

logger = logging.getLogger(__name__)

_JWT_ALGO = "HS256"
AUTH_TOKEN_HOURS = 24 * 7    # 7 days — any authenticated user (owner + signed-in)
GUEST_TOKEN_HOURS = 48        # 2 days — visitors
_RATE_WINDOW = 900            # 15 minutes
_RATE_MAX = 5                 # max login attempts per window

# Per-process sliding-window store used as a fail-closed fallback when Mongo is
# unavailable, so brute-force protection survives a DB outage.
_ip_hits: dict[str, deque] = {}
_ip_hits_lock = threading.Lock()


def _memory_rate_check(ip: str, scope: str = "login") -> Tuple[bool, int]:
    """Per-process sliding-window fallback used when Mongo is unavailable.
    Bounds brute force even during a DB outage (fail-closed-ish)."""
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
    # No fallback: an empty secret means anyone could forge a token, so we
    # refuse to sign or verify until JWT_SECRET is set.
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set; refusing to issue or verify tokens")
    return secret


def make_token(role: str, user_id: Optional[str] = None) -> str:
    hours = GUEST_TOKEN_HOURS if role == "guest" else AUTH_TOKEN_HOURS
    payload = {
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    if user_id:
        payload["user_id"] = str(user_id)
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGO)


def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except RuntimeError:
        # JWT_SECRET missing: reject every token instead of failing open.
        return None


def _claims_from_request() -> Optional[dict]:
    """Extract + verify a token from the Authorization header, falling back to a
    ``token`` field in the JSON body (same precedence the endpoints used inline)."""
    auth_header = request.headers.get("Authorization", "")
    token_str = auth_header.removeprefix("Bearer ").strip()
    if not token_str:
        body = request.get_json(silent=True) or {}
        token_str = (body.get("token") or "").strip()
    if not token_str:
        return None
    return verify_token(token_str)


def require_auth(view):
    """Reject the request with 401 unless a valid token is present.

    On success the decoded claims are passed to the view as ``claims=``.
    """

    @functools.wraps(view)
    def _wrapped(*args, **kwargs):
        claims = _claims_from_request()
        if not claims:
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, claims=claims, **kwargs)

    return _wrapped


def require_tenant(view):
    """Auth + tenant scoping for a *mutating* endpoint (the common write path).

    Composes on top of :func:`require_auth`: an unauthenticated request is
    rejected with 401, a guest with 403 (guests get read-only demo tabs, never
    writes), and the view then runs inside
    ``active_user_profile_context(build_user_profile(claims))`` so every store
    call resolves ``current_user_id()`` to THIS caller and stays tenant-scoped.
    The view still receives ``claims=`` exactly as under :func:`require_auth`.

    This replaces the per-endpoint boilerplate — ``if _is_guest(claims): return
    403`` followed by ``with active_user_profile_context(build_user_profile(
    claims)):`` — that was copied across every write handler, where one omission
    was a guest-write hole or an unscoped (cross-tenant) call.
    """

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


def check_owner_password(password: str) -> bool:
    owner_pass = os.getenv("OWNER_PASSWORD", "")
    if not owner_pass:
        return False
    return hmac.compare_digest(
        hashlib.sha256(password.encode()).digest(),
        hashlib.sha256(owner_pass.encode()).digest(),
    )


# Auth state (login rate limit + web access requests) lives in MongoDB. It used
# to be in Redis, but we dropped Redis/Upstash. One collection, `sandy_auth`, with
# a TTL index on `expire_at` (absolute expiry datetime) so entries self-clean.
_AUTH_COLL = "sandy_auth"
_auth_index_ready = False


def _auth_coll():
    """MongoDB collection for auth state, or None if Mongo isn't wired up."""
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


def check_rate_limit(ip: str, scope: str = "login") -> Tuple[bool, int]:
    """Returns (allowed, attempts_remaining). Falls back to an in-memory
    per-process limiter when Mongo is unavailable (fail-closed-ish).

    ``scope`` separates independent limiters (e.g. "login" vs "access" vs
    "email") so spamming one endpoint can't consume another's budget.
    """
    coll = _auth_coll()
    if coll is None:
        logger.warning(
            "[auth] Mongo unavailable; using in-memory rate limit fallback"
        )
        return _memory_rate_check(ip, scope)
    try:
        from datetime import datetime, timezone, timedelta
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


def _areq_key(request_id: str) -> str:
    return f"areq:{request_id}"


def store_access_request(name: str, reason: str = "") -> str:
    """Store a pending web access request, return its request_id."""
    request_id = uuid.uuid4().hex
    coll = _auth_coll()
    if coll is not None:
        try:
            from datetime import datetime, timezone, timedelta
            coll.update_one(
                {"_id": _areq_key(request_id)},
                {"$set": {
                    "name": name, "reason": reason, "status": "pending", "token": None,
                    "expire_at": datetime.now(timezone.utc) + timedelta(seconds=3600),
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.warning("[auth] store_access_request failed: %s", exc)
    return request_id


def get_access_request(request_id: str) -> Optional[dict]:
    coll = _auth_coll()
    if coll is None:
        return None
    try:
        return coll.find_one(
            {"_id": _areq_key(request_id)}, {"_id": 0, "expire_at": 0}
        )
    except Exception:
        return None


def approve_access_request(request_id: str) -> Optional[str]:
    """Approve the request, mint a guest token, and return it."""
    coll = _auth_coll()
    if coll is None:
        return None
    key = _areq_key(request_id)
    try:
        if not coll.find_one({"_id": key}, {"_id": 1}):
            return None
        try:
            token = make_token("guest")
        except RuntimeError:
            return None
        from datetime import datetime, timezone, timedelta
        coll.update_one(
            {"_id": key},
            {"$set": {
                "status": "approved", "token": token,
                "expire_at": datetime.now(timezone.utc) + timedelta(seconds=3600),
            }},
        )
        return token
    except Exception as exc:
        logger.warning("[auth] approve_access_request failed: %s", exc)
        return None


def deny_access_request(request_id: str) -> bool:
    coll = _auth_coll()
    if coll is None:
        return False
    key = _areq_key(request_id)
    try:
        if not coll.find_one({"_id": key}, {"_id": 1}):
            return False
        from datetime import datetime, timezone, timedelta
        coll.update_one(
            {"_id": key},
            {"$set": {
                "status": "denied",
                "expire_at": datetime.now(timezone.utc) + timedelta(seconds=300),
            }},
        )
        return True
    except Exception as exc:
        logger.warning("[auth] deny_access_request failed: %s", exc)
        return False
