"""Web API for native social sign-in — Google + Apple, multi-user.

The iOS app runs "Sign in with Google" / "Sign in with Apple" on-device and
hands us the resulting **ID token** (a signed JWT from the provider). These two
routes verify that token against the provider's published keys, find-or-create
the matching ``sandy_users`` record, and mint *our* app JWT so the rest of the
backend can treat the request as a known signed-in user.

  POST /api/auth/google → body {"id_token": "..."}
  POST /api/auth/apple  → body {"id_token": "...", "name"?: "..."}

Both return the same shape::

    {"token", "user_id", "role": "user", "onboarding_done": bool}

Verification uses PyJWT's ``PyJWKClient`` to fetch each provider's JWKS (their
RS256 public keys), checks the signature + ``exp`` + issuer + audience, then
trusts the claims inside. The JWKS clients are cached in-module with a TTL so we
don't refetch Google/Apple's keys on every request.

RS256 signature verification needs the ``cryptography`` package (already a
dependency alongside PyJWT). Follows the same module shape as
``onboarding_api`` — a single ``register_social_auth_api(app)`` that defines the
routes; the app factory wires it up.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import jwt  # PyJWT
from flask import jsonify, request

from app.api.auth_handlers import make_token
from app.features import users_store

logger = logging.getLogger(__name__)

_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"

# How long a cached JWKS client is reused before we rebuild it (and so refetch
# the provider's keys on the next verification). Providers rotate signing keys
# infrequently; an hour keeps us fresh without hammering their endpoints.
_JWKS_TTL_SECONDS = 3600

# url -> (PyJWKClient, created_at_monotonic)
_jwks_clients: dict[str, tuple["jwt.PyJWKClient", float]] = {}


def _get_jwks_client(jwks_url: str) -> "jwt.PyJWKClient":
    """Return a cached ``PyJWKClient`` for ``jwks_url``, rebuilding past the TTL.

    ``PyJWKClient`` itself caches the keys it fetches; we cache the client and
    expire it on a TTL so a rotated/retired provider key eventually drops out.
    """
    cached = _jwks_clients.get(jwks_url)
    now = time.monotonic()
    if cached is not None and (now - cached[1]) < _JWKS_TTL_SECONDS:
        return cached[0]
    client = jwt.PyJWKClient(jwks_url)
    _jwks_clients[jwks_url] = (client, now)
    return client


def _verify_id_token(
    id_token: str,
    *,
    jwks_url: str,
    issuer,
    audience: Optional[str],
    provider: str,
) -> Optional[dict]:
    """Verify a provider ID token and return its claims, or None if invalid.

    Raises ``ConnectionError`` (mapped to 503 by the caller) when the provider's
    JWKS can't be fetched — that's an availability problem, not a bad token. A
    forged/expired/malformed token returns None (mapped to 401).

    ``audience`` may be None: when the expected client id / bundle id env var is
    unset we skip the audience check (and log a warning) rather than reject.
    """
    try:
        signing_key = _get_jwks_client(jwks_url).get_signing_key_from_jwt(id_token)
    except jwt.PyJWKClientError as exc:
        # Couldn't resolve the signing key — usually a JWKS fetch/network issue,
        # but can also mean a token whose `kid` isn't in the provider's set.
        # Treat fetch failures as availability errors; the caller decides.
        logger.warning("[social_auth] %s JWKS key lookup failed: %s", provider, exc)
        raise ConnectionError(f"{provider} JWKS unavailable") from exc
    except jwt.InvalidTokenError as exc:
        logger.info("[social_auth] %s token rejected at key step: %s", provider, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — network/JWKS errors surface here
        logger.warning("[social_auth] %s JWKS fetch failed: %s", provider, exc)
        raise ConnectionError(f"{provider} JWKS unavailable") from exc

    decode_kwargs: dict = {
        "algorithms": ["RS256"],
        "issuer": issuer,
        "options": {"require": ["exp"]},
    }
    if audience:
        decode_kwargs["audience"] = audience
    else:
        logger.warning(
            "[social_auth] %s audience check SKIPPED (expected-aud env unset)",
            provider,
        )

    try:
        return jwt.decode(id_token, signing_key.key, **decode_kwargs)
    except jwt.InvalidTokenError as exc:
        # Expired, wrong issuer/audience, bad signature, malformed — all 401.
        logger.info("[social_auth] %s token rejected: %s", provider, exc)
        return None


def register_social_auth_api(app):
    @app.route("/api/auth/google", methods=["POST"])
    def api_auth_google():
        body = request.get_json(silent=True) or {}
        id_token = str(body.get("id_token") or "").strip()
        if not id_token:
            return jsonify({"error": "invalid_token"}), 401

        audience = os.getenv("GOOGLE_OAUTH_CLIENT_ID") or None
        try:
            claims = _verify_id_token(
                id_token,
                jwks_url=_GOOGLE_JWKS_URL,
                issuer=list(_GOOGLE_ISSUERS),
                audience=audience,
                provider="google",
            )
        except ConnectionError:
            return jsonify({"error": "auth_unavailable"}), 503

        if not claims:
            return jsonify({"error": "invalid_token"}), 401

        sub = str(claims.get("sub") or "").strip()
        if not sub:
            return jsonify({"error": "invalid_token"}), 401

        return _issue_for_identity(
            provider="google",
            sub=sub,
            email=str(claims.get("email") or ""),
            name=str(claims.get("name") or ""),
            picture=str(claims.get("picture") or ""),
        )

    @app.route("/api/auth/apple", methods=["POST"])
    def api_auth_apple():
        body = request.get_json(silent=True) or {}
        id_token = str(body.get("id_token") or "").strip()
        if not id_token:
            return jsonify({"error": "invalid_token"}), 401

        audience = os.getenv("APPLE_BUNDLE_ID") or None
        try:
            claims = _verify_id_token(
                id_token,
                jwks_url=_APPLE_JWKS_URL,
                issuer=_APPLE_ISSUER,
                audience=audience,
                provider="apple",
            )
        except ConnectionError:
            return jsonify({"error": "auth_unavailable"}), 503

        if not claims:
            return jsonify({"error": "invalid_token"}), 401

        sub = str(claims.get("sub") or "").strip()
        if not sub:
            return jsonify({"error": "invalid_token"}), 401

        # Apple only sends the name on the *first* authorization, in the app's
        # request body (never in the token), so prefer the body-supplied name.
        return _issue_for_identity(
            provider="apple",
            sub=sub,
            email=str(claims.get("email") or ""),
            name=str(body.get("name") or ""),
            picture="",
        )


def _issue_for_identity(*, provider: str, sub: str, email: str, name: str, picture: str):
    """Find-or-create the user for a verified identity and mint our app token."""
    user = users_store.upsert_from_oauth(
        provider, sub, email=email, name=name, picture=picture
    )
    if not user:
        # Store unavailable (Mongo down) — can't establish the account.
        logger.warning("[social_auth] %s upsert returned no user (store down?)", provider)
        return jsonify({"error": "auth_unavailable"}), 503

    user_id = user.get("_id")
    try:
        token = make_token("user", user_id=user_id)
    except RuntimeError:
        # JWT_SECRET not configured — we verified the user but can't sign a token.
        logger.error("[social_auth] cannot mint token: JWT_SECRET unset")
        return jsonify({"error": "auth_unavailable"}), 503

    onboarding = user.get("onboarding") or {}
    return jsonify({
        "token": token,
        "user_id": user_id,
        "role": "user",
        "onboarding_done": bool(onboarding.get("done", False)),
    }), 200
