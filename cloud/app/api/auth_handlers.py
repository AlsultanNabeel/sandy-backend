"""Sandy web auth: JWT access control with a Telegram approval flow."""
from __future__ import annotations

import functools
import hashlib
import hmac
import logging
import os
import uuid
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
        from app.agent.facade.agent import mongo_db
        if mongo_db is None:
            return None
        coll = mongo_db[_AUTH_COLL]
        if not _auth_index_ready:
            try:
                coll.create_index("expire_at", expireAfterSeconds=0, background=True)
            except Exception:
                pass
            _auth_index_ready = True
        return coll
    except Exception:
        return None


def check_rate_limit(ip: str) -> Tuple[bool, int]:
    """Returns (allowed, attempts_remaining). Fails open if Mongo unavailable."""
    coll = _auth_coll()
    if coll is None:
        logger.warning(
            "[auth] rate limit failing OPEN: store unavailable; "
            "login brute-force protection is disabled"
        )
        return True, _RATE_MAX
    try:
        from datetime import datetime, timezone, timedelta
        from pymongo import ReturnDocument
        now = datetime.now(timezone.utc)
        doc = coll.find_one_and_update(
            {"_id": f"rate:{ip}"},
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
            "[auth] rate limit failing OPEN: store error (%s); "
            "login brute-force protection is disabled",
            exc,
        )
        return True, _RATE_MAX


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
