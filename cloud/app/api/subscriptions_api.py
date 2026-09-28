"""Subscription state mirrored from RevenueCat (the billing source of truth).

  POST /webhook/revenuecat  machine caller; Authorization must equal REVENUECAT_WEBHOOK_AUTH.
                            Always 200 after auth so RevenueCat doesn't retry-storm.
  GET  /api/subscription    the signed-in user's status.

RevenueCat's ``app_user_id`` is our ``user_id``.
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

# RevenueCat event type → status; a trial period overrides to "trialing".
_ACTIVE_EVENTS = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "UNCANCELLATION",
    "PRODUCT_CHANGE",
    # Auto-renew off, but access lasts until the period ends.
    "CANCELLATION",
}
_EXPIRED_EVENTS = {
    "EXPIRATION",
    "BILLING_ISSUE",
}


def _dt_from_ms(ms: object) -> Optional[datetime]:
    """Epoch milliseconds → aware UTC datetime."""
    try:
        if ms in (None, ""):
            return None
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _is_trial(event: dict) -> bool:
    period = str(
        event.get("period_type")
        or event.get("periodType")
        or ""
    ).upper()
    return period == "TRIAL"


def register_subscriptions_api(app):
    @app.route("/webhook/revenuecat", methods=["POST"])
    def revenuecat_webhook():
        # Fail closed without the secret, or anyone could grant a free subscription.
        expected = os.getenv("REVENUECAT_WEBHOOK_AUTH", "")
        if not expected:
            logger.error("[revenuecat] REVENUECAT_WEBHOOK_AUTH not set; refusing webhook")
            return jsonify({"error": "webhook_not_configured"}), 503
        provided = request.headers.get("Authorization", "")
        if not hmac.compare_digest(provided, expected):
            logger.warning("[revenuecat] webhook auth failed")
            return jsonify({"error": "unauthorized"}), 401

        # Never raise from here: RevenueCat retries non-2xx aggressively.
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
                # Non-subscription event (TEST, TRANSFER, ...): ack only.
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
            "is_subscriber": users_store.has_live_subscription(user),
        }), 200
