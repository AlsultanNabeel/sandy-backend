"""Native Google/Apple sign-in: verify the provider ID token and mint our app JWT.

  POST /api/auth/google {"id_token"} · POST /api/auth/apple {"id_token", "name"?}
  → {"token", "user_id", "role", "onboarding_done"}

Tokens are checked against the provider JWKS (signature, exp, issuer, audience).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import jwt
from flask import jsonify, request

from app.api.auth_handlers import make_token, role_for_email
from app.config import APP_ENV, APPLE_BUNDLE_ID, GOOGLE_OAUTH_CLIENT_ID
from app.features import users_store

logger = logging.getLogger(__name__)

_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"

# Cached JWKS clients are rebuilt after this, so rotated keys eventually drop out.
_JWKS_TTL_SECONDS = 3600

# url -> (PyJWKClient, created_at_monotonic)
_jwks_clients: dict[str, tuple["jwt.PyJWKClient", float]] = {}


def _get_jwks_client(jwks_url: str) -> "jwt.PyJWKClient":
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
    """Provider token claims, or None if invalid (→ 401).

    Raises ConnectionError (→ 503) when the JWKS can't be fetched. ``audience=None``
    skips the audience check (dev only; never earns the owner tier).
    """
    try:
        signing_key = _get_jwks_client(jwks_url).get_signing_key_from_jwt(id_token)
    except jwt.PyJWKClientError as exc:
        # Usually a JWKS fetch problem (or an unknown `kid`): treat as unavailable.
        logger.warning("[social_auth] %s JWKS key lookup failed: %s", provider, exc)
        raise ConnectionError(f"{provider} JWKS unavailable") from exc
    except jwt.InvalidTokenError as exc:
        logger.info("[social_auth] %s token rejected at key step: %s", provider, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[social_auth] %s JWKS fetch failed: %s", provider, exc)
        raise ConnectionError(f"{provider} JWKS unavailable") from exc

    decode_kwargs: dict = {
        "algorithms": ["RS256"],
        "issuer": issuer,
        "options": {"require": ["exp"]},
    }
    if audience:
        decode_kwargs["audience"] = audience

    try:
        return jwt.decode(id_token, signing_key.key, **decode_kwargs)
    except jwt.InvalidTokenError as exc:
        logger.info("[social_auth] %s token rejected: %s", provider, exc)
        return None


class _AudienceNotConfigured(RuntimeError):
    """Raised in prod when the provider's expected audience is not configured."""


def _expected_audience(configured: str, provider: str) -> Optional[str]:
    """The audience tokens must carry, or None to skip (dev only; in prod a missing value refuses).

    Without the audience check, another app's valid token for the same person would sign in here.
    """
    if configured:
        return configured
    if APP_ENV == "prod":
        raise _AudienceNotConfigured(provider)
    logger.warning(
        "[social_auth] %s audience check SKIPPED (expected-aud env unset, APP_ENV=%s)",
        provider, APP_ENV,
    )
    return None


def register_social_auth_api(app):
    @app.route("/api/auth/google", methods=["POST"])
    def api_auth_google():
        body = request.get_json(silent=True) or {}
        id_token = str(body.get("id_token") or "").strip()
        if not id_token:
            return jsonify({"error": "invalid_token"}), 401

        try:
            audience = _expected_audience(GOOGLE_OAUTH_CLIENT_ID, "google")
        except _AudienceNotConfigured:
            logger.error("[social_auth] GOOGLE_OAUTH_CLIENT_ID unset in prod — "
                         "refusing rather than accepting any app's token")
            return jsonify({"error": "auth_not_configured"}), 503

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
            email_trusted=bool(audience) and _is_true(claims.get("email_verified")),
        )

    @app.route("/api/auth/apple", methods=["POST"])
    def api_auth_apple():
        body = request.get_json(silent=True) or {}
        id_token = str(body.get("id_token") or "").strip()
        if not id_token:
            return jsonify({"error": "invalid_token"}), 401

        try:
            audience = _expected_audience(APPLE_BUNDLE_ID, "apple")
        except _AudienceNotConfigured:
            logger.error("[social_auth] APPLE_BUNDLE_ID unset in prod — "
                         "refusing rather than accepting any app's token")
            return jsonify({"error": "auth_not_configured"}), 503

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

        # Apple sends the name only on first authorization, in the request body.
        return _issue_for_identity(
            provider="apple",
            sub=sub,
            email=str(claims.get("email") or ""),
            name=str(body.get("name") or ""),
            picture="",
            email_trusted=bool(audience) and _is_true(claims.get("email_verified")),
        )


def _is_true(value) -> bool:
    """Google sends `email_verified` as a bool, Apple as "true"."""
    return value is True or str(value).strip().lower() == "true"


def _issue_for_identity(*, provider: str, sub: str, email: str, name: str,
                        picture: str, email_trusted: bool = False):
    """Find-or-create the user and mint our token.

    The owner tier needs a provider-verified email and an audience-checked token.
    """
    user = users_store.upsert_from_oauth(
        provider, sub, email=email, name=name, picture=picture
    )
    if not user:
        logger.warning("[social_auth] %s upsert returned no user (store down?)", provider)
        return jsonify({"error": "auth_unavailable"}), 503

    user_id = user.get("_id")
    role = role_for_email(email) if email_trusted else "user"
    try:
        token = make_token(role, user_id=user_id, gen=user.get(users_store.TOKEN_GEN_FIELD) or 0)
    except RuntimeError:
        logger.error("[social_auth] cannot mint token: JWT_SECRET unset")
        return jsonify({"error": "auth_unavailable"}), 503

    onboarding = user.get("onboarding") or {}
    return jsonify({
        "token": token,
        "user_id": user_id,
        "role": role,
        "onboarding_done": bool(onboarding.get("done", False)),
    }), 200
