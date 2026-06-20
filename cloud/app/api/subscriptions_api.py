"""Web API for subscription state — RevenueCat-backed.

The mobile app sells a monthly subscription through RevenueCat (on the iOS
side). RevenueCat is the source of truth for billing; this backend just mirrors
each user's status so premium features can be gated server-side.

Two endpoints:

  POST /webhook/revenuecat  — RevenueCat's server-to-server webhook. No JWT
      (it's a machine caller); instead, when ``REVENUECAT_WEBHOOK_AUTH`` is set
      we require the ``Authorization`` header to equal it. We're deliberately
      lenient about the body and ALWAYS answer 200 (except on a failed auth
      check) so RevenueCat doesn't retry-storm us over a single bad event.

  GET /api/subscription  — the signed-in user's current status, for the app to
      show/hide premium UI. Mirrors what ``is_subscriber`` gates on.

The webhook maps RevenueCat event ``type`` → our subscription status and writes
it via ``users_store.set_subscription``. ``app_user_id`` from RevenueCat is our
own ``user_id`` (the app sets it when configuring the RevenueCat SDK).
"""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.features import users_store

logger = logging.getLogger(__name__)

# RevenueCat event type → our subscription status.
#   active   — paid (or still inside a cancelled period that hasn't expired yet)
#   expired  — access has lapsed
# A trial flag on the event overrides this to "trialing" (handled below).
_ACTIVE_EVENTS = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "UNCANCELLATION",
    "PRODUCT_CHANGE",
    # CANCELLATION means auto-renew was turned off but the user keeps access
    # until current_period_end, so it stays "active" too.
    "CANCELLATION",
}
_EXPIRED_EVENTS = {
    "EXPIRATION",
    "BILLING_ISSUE",
}


def _dt_from_ms(ms: object) -> Optional[datetime]:
    """RevenueCat timestamps are epoch milliseconds → aware UTC datetime."""
    try:
        if ms in (None, ""):
            return None
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _is_trial(event: dict) -> bool:
    """RevenueCat signals a trial via a 'TRIAL' period type (field naming
    varies across payload versions, so check the common spots)."""
    period = str(
        event.get("period_type")
        or event.get("periodType")
        or ""
    ).upper()
    return period == "TRIAL"


def register_subscriptions_api(app):
    @app.route("/webhook/revenuecat", methods=["POST"])
    def revenuecat_webhook():
        # Shared-secret auth (RevenueCat sends it in the Authorization header).
        expected = os.getenv("REVENUECAT_WEBHOOK_AUTH", "")
        if expected:
            provided = request.headers.get("Authorization", "")
            if not hmac.compare_digest(provided, expected):
                logger.warning("[revenuecat] webhook auth failed")
                return jsonify({"error": "unauthorized"}), 401

        # From here on, never raise: RevenueCat retries non-2xx aggressively, so
        # we swallow anything malformed and still answer 200.
        try:
            body = request.get_json(silent=True) or {}
            event = body.get("event") or {}

            app_user_id = (event.get("app_user_id") or "").strip()
            event_type = str(event.get("type") or "").upper()
            product_id = event.get("product_id") or ""
            if not product_id:
                ent = event.get("entitlement_ids") or event.get("entitlement_id")
                if isinstance(ent, list):
                    product_id = ent[0] if ent else ""
                elif ent:
                    product_id = str(ent)

            period_end = _dt_from_ms(
                event.get("expiration_at_ms") or event.get("expiration_at")
            )

            if not app_user_id:
                logger.warning(
                    "[revenuecat] event %s missing app_user_id; ignoring",
                    event_type or "<none>",
                )
                return jsonify({"ok": True}), 200

            if _is_trial(event):
                status = "trialing"
            elif event_type in _ACTIVE_EVENTS:
                status = "active"
            elif event_type in _EXPIRED_EVENTS:
                status = "expired"
            else:
                # Unknown / non-subscription event (e.g. TEST, TRANSFER): ack
                # without touching state.
                logger.info("[revenuecat] ignoring event type %s", event_type or "<none>")
                return jsonify({"ok": True}), 200

            ok = users_store.set_subscription(
                app_user_id,
                status=status,
                plan=product_id or "",
                current_period_end=period_end,
                source="revenuecat",
            )
            logger.info(
                "[revenuecat] %s → user=%s status=%s saved=%s",
                event_type, app_user_id, status, ok,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[revenuecat] webhook error: %s", exc)

        return jsonify({"ok": True}), 200

    @app.route("/api/subscription", methods=["GET"])
    @require_auth
    def api_get_subscription(claims):
        user_id = claims.get("user_id") or ""
        user = users_store.get_user(user_id) or {}
        sub = user.get("subscription") or {}
        return jsonify({
            "status": sub.get("status", "none"),
            "plan": sub.get("plan", ""),
            "is_subscriber": users_store.is_subscriber(user_id),
        }), 200
