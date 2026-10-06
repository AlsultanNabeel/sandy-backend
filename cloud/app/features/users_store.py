"""User accounts (sandy_users): identity, onboarding profile, persona, subscription.

{_id: user_id, provider, provider_sub, email, name, picture, locale,
 onboarding: {done, preferred_name, interests, notes, nudge_answers},
 persona: {dialect, custom_instructions}, subscription: {status, plan,
 trial_ends_at, current_period_end, source}, created_at, last_seen_at}
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.db import configure, get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_users"

def init_users_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("provider", 1), ("provider_sub", 1)], unique=True, background=True
        )
        mongo_db[_COLL].create_index([("email", 1)], background=True)
        logger.info("[UsersStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[UsersStore] index skipped: {e}")


def is_available() -> bool:
    return get_db() is not None


def _bump(user_id: str, collection: str = "sandy_users") -> None:
    """Mark this tenant's cached persona stale (this module writes on the raw collection)."""
    try:
        from app.utils.tenant_version import bump_for

        bump_for(str(user_id or ""), collection=collection)
    except Exception:  # noqa: BLE001 — a stale cache must not fail the write
        logger.debug("[users_store] version bump skipped", exc_info=True)


def _profile_changed(user_id: str) -> None:
    """The name, the get-to-know-you answers or the persona changed: the voice
    instruction carries them, so none built before this may stand in for a new one."""
    from app.utils.tenant_version import mark_corrected

    mark_corrected(str(user_id or ""))


def _coll():
    return get_db()[_COLL] if get_db() is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Mongo returns naive datetimes that are actually UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ── reads ────────────────────────────────────────────────────────────────

def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None or not user_id:
        return None
    return coll.find_one({"_id": user_id})


# The account's token generation: a token carries the one it was issued on, and only a
# token on the current one is renewed. Moving it on revokes every token issued before.
TOKEN_GEN_FIELD = "token_gen"


def move_token_generation(user_id: str) -> bool:
    """Revoke every token issued so far; False when the account or the store is not there."""
    coll = _coll()
    if coll is None or not user_id:
        return False
    try:
        return coll.update_one({"_id": user_id}, {"$inc": {TOKEN_GEN_FIELD: 1}}).matched_count > 0
    except PyMongoError as exc:
        logger.warning("[users] generation not moved for %s: %s", user_id, exc)
        return False


class GenerationUnreadable(Exception):
    """The account's generation could not be read (no database, or the read failed)."""


def token_generation(user_id: str) -> Optional[int]:
    """The account's token generation (0 until it ever moves), None when there is no
    account; raises `GenerationUnreadable` when it cannot be read."""
    coll = _coll()
    if coll is None:
        raise GenerationUnreadable("no database")
    if not user_id:
        return None
    try:
        doc = coll.find_one({"_id": user_id}, {TOKEN_GEN_FIELD: 1})
    except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
        raise GenerationUnreadable(str(exc)) from exc
    return int(doc.get(TOKEN_GEN_FIELD) or 0) if doc else None


# ── writes ───────────────────────────────────────────────────────────────

def fresh_onboarding() -> Dict[str, Any]:
    """The get-to-know-you part of a new account (and of one just reset)."""
    return {"done": False, "preferred_name": "", "interests": [], "notes": ""}


def upsert_from_oauth(
    provider: str,
    provider_sub: str,
    email: str = "",
    name: str = "",
    picture: str = "",
    locale: str = "ar",
) -> Optional[Dict[str, Any]]:
    """Find-or-create a user from a verified OAuth identity; later sign-ins refresh the profile."""
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
        _bump(str(existing["_id"]))
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
        "onboarding": fresh_onboarding(),
        "subscription": {"status": "none", "plan": "", "trial_ends_at": None,
                         "current_period_end": None, "source": ""},
        "created_at": now,
        "last_seen_at": now,
    }
    try:
        coll.insert_one(doc)
    except DuplicateKeyError:
        # Two first sign-ins raced; return the one that won.
        return coll.find_one({"provider": provider, "provider_sub": provider_sub})
    return doc


def get_email_user(email: str) -> Optional[Dict[str, Any]]:
    """Find an email/password user by (normalized) email, or None."""
    coll = _coll()
    e = (email or "").strip().lower()
    if coll is None or not e:
        return None
    return coll.find_one({"provider": "email", "provider_sub": e})


def create_email_user(
    email: str, password_hash: str, name: str = ""
) -> Optional[Dict[str, Any]]:
    """New email/password user, or None if the email is taken or the store is down."""
    coll = _coll()
    e = (email or "").strip().lower()
    if coll is None or not e or not password_hash:
        return None
    if coll.find_one({"provider": "email", "provider_sub": e}):
        return None  # already exists

    now = _now()
    user_id = uuid.uuid4().hex
    doc: Dict[str, Any] = {
        "_id": user_id,
        "provider": "email",
        "provider_sub": e,
        "email": e,
        "name": name,
        "picture": "",
        "locale": "ar",
        "password_hash": password_hash,
        "onboarding": fresh_onboarding(),
        "subscription": {"status": "none", "plan": "", "trial_ends_at": None,
                         "current_period_end": None, "source": ""},
        "created_at": now,
        "last_seen_at": now,
    }
    try:
        coll.insert_one(doc)
    except DuplicateKeyError:
        return None  # a concurrent sign-up took this email first
    return doc


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
    _bump(user_id)
    _profile_changed(user_id)
    return res.matched_count > 0


def get_budget(user_id: str) -> float:
    """The monthly spending limit the user set; 0 when there is none."""
    coll = _coll()
    if coll is None or not user_id:
        return 0.0
    doc = coll.find_one({"_id": user_id}, {"budget": 1}) or {}
    value = doc.get("budget")
    return float(value) if isinstance(value, (int, float)) and value > 0 else 0.0


def set_budget(user_id: str, amount: float) -> bool:
    """0 removes the limit."""
    coll = _coll()
    if coll is None or not user_id:
        return False
    res = coll.update_one({"_id": user_id}, {"$set": {"budget": max(float(amount), 0.0)}})
    _bump(user_id)
    return res.matched_count > 0


def set_timezone(user_id: str, zone: str) -> bool:
    """The zone the user's phone is in (an IANA name, already checked)."""
    coll = _coll()
    if coll is None or not user_id:
        return False
    res = coll.update_one({"_id": user_id}, {"$set": {"timezone": zone}})
    _bump(user_id)
    return res.matched_count > 0


def set_city(user_id: str, city: str) -> bool:
    """The city the app shows weather for; Sandy's «شو الطقس؟» with no city."""
    coll = _coll()
    if coll is None or not user_id:
        return False
    # Written only when it changed: the app asks for the weather often.
    coll.update_one({"_id": user_id, "city": {"$ne": city[:80]}}, {"$set": {"city": city[:80]}})
    return True


def get_nudge_answers(user_id: str) -> Dict[str, Any]:
    """{qid: answer} for the daily-nudge questions."""
    coll = _coll()
    if coll is None or not user_id:
        return {}
    doc = coll.find_one({"_id": user_id}, {"onboarding.nudge_answers": 1}) or {}
    return ((doc.get("onboarding") or {}).get("nudge_answers")) or {}


def record_nudge_answer(user_id: str, qid: str, answer: str) -> bool:
    coll = _coll()
    qid = (qid or "").strip()
    answer = (answer or "").strip()[:300]
    if coll is None or not user_id or not qid or not answer:
        return False
    res = coll.update_one(
        {"_id": user_id},
        {"$set": {f"onboarding.nudge_answers.{qid}": answer, "last_seen_at": _now()}},
    )
    _bump(user_id)
    _profile_changed(user_id)
    return res.matched_count > 0


_DEFAULT_PERSONA: Dict[str, Any] = {"dialect": "palestinian", "custom_instructions": ""}


def get_persona(user_id: str) -> Dict[str, Any]:
    """Dialect + custom instructions, or the defaults."""
    coll = _coll()
    if coll is None or not user_id:
        return dict(_DEFAULT_PERSONA)
    user = coll.find_one({"_id": user_id}, {"persona": 1}) or {}
    persona = user.get("persona") or {}
    return {
        "dialect": str(persona.get("dialect") or _DEFAULT_PERSONA["dialect"]),
        "custom_instructions": str(persona.get("custom_instructions") or ""),
    }


def set_persona(
    user_id: str,
    dialect: Optional[str] = None,
    custom_instructions: Optional[str] = None,
) -> bool:
    """Pass ``""`` for custom_instructions to reset it."""
    coll = _coll()
    if coll is None or not user_id:
        return False
    sets: Dict[str, Any] = {}
    if dialect is not None:
        sets["persona.dialect"] = dialect.strip()[:30]
    if custom_instructions is not None:
        sets["persona.custom_instructions"] = custom_instructions.strip()[:2000]
    if not sets:
        return True
    res = coll.update_one({"_id": user_id}, {"$set": sets})
    _bump(user_id)
    _profile_changed(user_id)
    return res.matched_count > 0


def set_subscription(
    user_id: str,
    status: str,
    plan: str = "",
    trial_ends_at: Optional[datetime] = None,
    current_period_end: Optional[datetime] = None,
    source: str = "",
    event_at: Optional[datetime] = None,
) -> str:
    """Save the subscription as of `event_at`: "saved", "stale" (a newer event is already
    saved: events arrive out of order), or "unknown_user". Raises when the store is down,
    so the caller can ask for the event again."""
    coll = _coll()
    if coll is None:
        raise RuntimeError("users store unavailable")
    if not user_id:
        return "unknown_user"
    sets = {
        "subscription.status": status,
        "subscription.plan": plan,
        "subscription.trial_ends_at": trial_ends_at,
        "subscription.current_period_end": current_period_end,
        "subscription.source": source,
    }
    match: Dict[str, Any] = {"_id": user_id}
    if event_at is not None:
        sets["subscription.event_at"] = event_at
        match["$or"] = [{"subscription.event_at": {"$exists": False}},
                        {"subscription.event_at": None},
                        {"subscription.event_at": {"$lte": event_at}}]
    res = coll.update_one(match, {"$set": sets})
    if res.matched_count:
        _bump(user_id)
        return "saved"
    return "stale" if coll.find_one({"_id": user_id}, {"_id": 1}) else "unknown_user"


def is_subscriber(user_id: str) -> bool:
    """True while the user has paid or trial access."""
    return has_live_subscription(get_user(user_id))


def has_live_subscription(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    sub = user.get("subscription") or {}
    if sub.get("status") not in ("active", "trialing"):
        return False
    end = _as_aware_utc(sub.get("current_period_end") or sub.get("trial_ends_at"))
    return end is None or end > _now()
