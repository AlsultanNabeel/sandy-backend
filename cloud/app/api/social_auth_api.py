"""Web API for native social sign-in — Google + Apple, multi-user.

The iOS app runs "Sign in with Google" / "Sign in with Apple" on-device and
hands us the resulting **ID token** (a signed JWT from the provider). These two
routes verify that token against the provider's published keys, find-or-create
the matching ``sandy_users`` record, and mint *our* app JWT so the rest of the
backend can treat the request as a known signed-in user.

  POST /api/auth/google → body {"id_token": "..."}
  POST /api/auth/apple  → body {"id_token": "...", "name"?: "..."}

Both return the same shape::

    {"token", "user_id", "role", "onboarding_done": bool}

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
import time
from typing import Optional

import jwt  # PyJWT
from flask import jsonify, request

from app.api.auth_handlers import make_token, role_for_email
from app.config import APP_ENV, APPLE_BUNDLE_ID, GOOGLE_OAUTH_CLIENT_ID
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

    ``audience`` may be None, which skips the audience check. Only
    `_expected_audience` decides that, and only outside prod — in prod the route
    refuses before reaching here. A skipped check also never earns the owner
    tier (see `_issue_for_identity`).
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
    # No `else` branch: `_expected_audience` is the one place that decides to
    # skip, and it logs there. Warning in both left two lines per sign-in saying
    # the same thing.

    try:
        return jwt.decode(id_token, signing_key.key, **decode_kwargs)
    except jwt.InvalidTokenError as exc:
        # Expired, wrong issuer/audience, bad signature, malformed — all 401.
        logger.info("[social_auth] %s token rejected: %s", provider, exc)
        return None


class _AudienceNotConfigured(RuntimeError):
    """Raised in prod when the provider's expected audience is not configured."""


def _expected_audience(configured: str, provider: str) -> Optional[str]:
    """The audience this provider's tokens must carry, or None to skip the check.

    **The skip is a development affordance, and it used to be the production
    behaviour.** Signature and issuer together prove only that a token is a
    genuine Google (or Apple) token; the audience is the single claim that says
    it was minted for *this* app. With the check skipped, an ID token that any
    other Google-signed-in app holds for the same person verifies here — and the
    caller of that app can sign in as them. Nothing in the flow looks wrong; the
    token really is valid, just not for us.

    The old behaviour narrowed the damage — such a sign-in never got the owner
    role — but the account it opens is still somebody's account, with their
    chats, their memory and their robot behind it. So in prod a missing value is
    a refusal to answer, not a check to drop. Outside prod it warns and skips,
    because a backend on a laptop should still sign in before an OAuth client
    exists.
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

        # Apple only sends the name on the *first* authorization, in the app's
        # request body (never in the token), so prefer the body-supplied name.
        return _issue_for_identity(
            provider="apple",
            sub=sub,
            email=str(claims.get("email") or ""),
            name=str(body.get("name") or ""),
            picture="",
            email_trusted=bool(audience) and _is_true(claims.get("email_verified")),
        )


def _is_true(value) -> bool:
    """Google sends `email_verified` as a boolean, Apple as the string "true"."""
    return value is True or str(value).strip().lower() == "true"


def _issue_for_identity(*, provider: str, sub: str, email: str, name: str,
                        picture: str, email_trusted: bool = False):
    """Find-or-create the user for a verified identity and mint our app token.

    **The owner tier is granted on an email the provider vouched for, and only
    then.** `role_for_email` matches the address in the token against
    `SANDY_OWNER_EMAILS`, and it used to accept any address the token carried —
    including one the provider marks `email_verified: false`, and including a
    token minted for somebody else's app when the audience check is skipped
    (`GOOGLE_OAUTH_CLIENT_ID` / `APPLE_BUNDLE_ID` unset). Either way the owner's
    address in a token was enough for the owner's quota tier. Unverified sign-ins
    still work; they just get the ordinary role.
    """
    user = users_store.upsert_from_oauth(
        provider, sub, email=email, name=name, picture=picture
    )
    if not user:
        # Store unavailable (Mongo down) — can't establish the account.
        logger.warning("[social_auth] %s upsert returned no user (store down?)", provider)
        return jsonify({"error": "auth_unavailable"}), 503

    user_id = user.get("_id")
    role = role_for_email(email) if email_trusted else "user"
    try:
        token = make_token(role, user_id=user_id)
    except RuntimeError:
        # JWT_SECRET not configured — we verified the user but can't sign a token.
        logger.error("[social_auth] cannot mint token: JWT_SECRET unset")
        return jsonify({"error": "auth_unavailable"}), 503

    onboarding = user.get("onboarding") or {}
    return jsonify({
        "token": token,
        "user_id": user_id,
        "role": role,
        "onboarding_done": bool(onboarding.get("done", False)),
    }), 200
