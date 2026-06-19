"""Native multi-user account store — MongoDB.

The first brick of the multi-user product (the mobile app): Sandy was built
around a single owner; this store gives every user a stable identity, an
onboarding profile (preferred name / interests), and a subscription status,
all isolated per ``user_id``.

This module is purely additive — it does not touch the existing owner flow.
Other stores get keyed by the ``user_id`` it mints in later steps.

Collection: sandy_users
  {_id: user_id (uuid str),
   provider ("google" | "apple"), provider_sub (OAuth subject, stable),
   email, name, picture, locale,
   onboarding: {done: bool, preferred_name: str, interests: [str], notes: str},
   subscription: {status: "none"|"trialing"|"active"|"expired",
                  plan: str, trial_ends_at, current_period_end, source},
   created_at, last_seen_at}

Wired at boot via init_users_store(mongo_db) — same pattern as the other stores.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_COLL = "sandy_users"
_mongo_db = None


def init_users_store(mongo_db) -> None:
    """يُستدعى مرّة عند الإقلاع."""
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("provider", 1), ("provider_sub", 1)], unique=True, background=True
        )
        mongo_db[_COLL].create_index([("email", 1)], background=True)
        print("[UsersStore] ready")
    except Exception as e:  # noqa: BLE001
        print(f"[UsersStore] index skipped: {e}")


def is_available() -> bool:
    return _mongo_db is not None


def _coll():
    return _mongo_db[_COLL] if _mongo_db is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Mongo returns naive datetimes that are actually UTC — fix that."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ── reads ────────────────────────────────────────────────────────────────

def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None or not user_id:
        return None
    return coll.find_one({"_id": user_id})


def get_by_provider(provider: str, provider_sub: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None or not provider or not provider_sub:
        return None
    return coll.find_one({"provider": provider, "provider_sub": provider_sub})


# ── writes ───────────────────────────────────────────────────────────────

def upsert_from_oauth(
    provider: str,
    provider_sub: str,
    email: str = "",
    name: str = "",
    picture: str = "",
    locale: str = "ar",
) -> Optional[Dict[str, Any]]:
    """Find-or-create a user from a verified OAuth identity.

    Returns the full user document (with a stable ``_id`` == user_id). The first
    sign-in mints a new uuid; later sign-ins refresh the profile + last_seen.
    """
    coll = _coll()
    if coll is None or not provider or not provider_sub:
        return None

    now = _now()
    existing = coll.find_one({"provider": provider, "provider_sub": provider_sub})
    if existing:
        updates = {"last_seen_at": now}
        # Refresh profile fields if the provider now gives us more.
        for field, value in (("email", email), ("name", name), ("picture", picture)):
            if value and not existing.get(field):
                updates[field] = value
        coll.update_one({"_id": existing["_id"]}, {"$set": updates})
        existing.update(updates)
        return existing

    user_id = uuid.uuid4().hex
    doc: Dict[str, Any] = {
        "_id": user_id,
        "provider": provider,
        "provider_sub": provider_sub,
        "email": email,
        "name": name,
        "picture": picture,
        "locale": locale,
        "onboarding": {"done": False, "preferred_name": "", "interests": [], "notes": ""},
        "subscription": {"status": "none", "plan": "", "trial_ends_at": None,
                         "current_period_end": None, "source": ""},
        "created_at": now,
        "last_seen_at": now,
    }
    coll.insert_one(doc)
    return doc


def touch_last_seen(user_id: str) -> None:
    coll = _coll()
    if coll is None or not user_id:
        return
    coll.update_one({"_id": user_id}, {"$set": {"last_seen_at": _now()}})


def set_onboarding(
    user_id: str,
    preferred_name: Optional[str] = None,
    interests: Optional[List[str]] = None,
    notes: Optional[str] = None,
    done: bool = True,
) -> bool:
    """Save first-run get-to-know-you answers; marks onboarding done by default."""
    coll = _coll()
    if coll is None or not user_id:
        return False
    sets: Dict[str, Any] = {"onboarding.done": bool(done)}
    if preferred_name is not None:
        sets["onboarding.preferred_name"] = preferred_name.strip()[:80]
    if interests is not None:
        sets["onboarding.interests"] = [str(i).strip()[:60] for i in interests if str(i).strip()][:20]
    if notes is not None:
        sets["onboarding.notes"] = notes.strip()[:500]
    res = coll.update_one({"_id": user_id}, {"$set": sets})
    return res.matched_count > 0


def set_subscription(
    user_id: str,
    status: str,
    plan: str = "",
    trial_ends_at: Optional[datetime] = None,
    current_period_end: Optional[datetime] = None,
    source: str = "",
) -> bool:
    """Update subscription state (called later by the RevenueCat webhook)."""
    coll = _coll()
    if coll is None or not user_id:
        return False
    sets = {
        "subscription.status": status,
        "subscription.plan": plan,
        "subscription.trial_ends_at": trial_ends_at,
        "subscription.current_period_end": current_period_end,
        "subscription.source": source,
    }
    res = coll.update_one({"_id": user_id}, {"$set": sets})
    return res.matched_count > 0


def is_subscriber(user_id: str) -> bool:
    """True while the user has paid or trial access (gates premium features)."""
    user = get_user(user_id)
    if not user:
        return False
    sub = user.get("subscription") or {}
    if sub.get("status") not in ("active", "trialing"):
        return False
    end = _as_aware_utc(sub.get("current_period_end") or sub.get("trial_ends_at"))
    return end is None or end > _now()
