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
   persona: {dialect: str (app.agent.context_builder.DIALECT_PRESETS key),
             custom_instructions: str} — absent means the defaults,
   subscription: {status: "none"|"trialing"|"active"|"expired",
                  plan: str, trial_ends_at, current_period_end, source},
   created_at, last_seen_at}

Wired at boot via init_users_store(mongo_db) — same pattern as the other stores.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.db import configure, get_db
import logging

logger = logging.getLogger(__name__)

_COLL = "sandy_users"


def init_users_store(mongo_db) -> None:
    """يُستدعى مرّة عند الإقلاع."""
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


def _coll():
    return get_db()[_COLL] if get_db() is not None else None


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
    """Create a new email/password user (same doc shape as OAuth users, plus
    ``password_hash``). Returns the doc, or None if the email is already taken
    or the store is down. The normalized email is the stable ``provider_sub``."""
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
        "onboarding": {"done": False, "preferred_name": "", "interests": [], "notes": ""},
        "subscription": {"status": "none", "plan": "", "trial_ends_at": None,
                         "current_period_end": None, "source": ""},
        "created_at": now,
        "last_seen_at": now,
    }
    coll.insert_one(doc)
    return doc


def get_or_create_owner(name: str = "") -> Optional[str]:
    """The owner is user #1 — a stable account keyed by provider='owner'.

    Returns the owner's stable ``user_id`` (or None if Mongo is unavailable).
    """
    import os
    sub = (os.getenv("OWNER_CHAT_ID") or os.getenv("SANDY_USER_CHAT_ID") or "owner").strip() or "owner"
    user = upsert_from_oauth("owner", sub, name=name)
    return (user or {}).get("_id")


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
    if res.matched_count:
        _mirror_onboarding_to_memory(user_id)
    return res.matched_count > 0


def _mirror_onboarding_to_memory(user_id: str) -> None:
    """اكتب الاسم والاهتمامات بالذاكرة كمان — **باستبدال، مش بإضافة**.

    الملف الشخصي بينحقن بالتعليمات، فهي بتعرفه بلا ما تدوّر. بس المالك بيسأل
    «شو اهتماماتي؟» ككلام عادي، والسؤال هيك بيمرق ع البحث بالذاكرة — ولو ما
    كانوا هناك، بتردّ «ما في ذكريات محفوظة» وهي عارفتهن. نفس المعلومة، وجوابين
    متناقضين حسب صيغة السؤال.

    والخطر الواضح إنه يصير مصدرين للحقيقة: تعدّل اهتماماتك بالإعدادات، والنسخة
    القديمة تضلّ بالذاكرة وتناقض الجديدة. عشان هيك السجلّ **مفتاحه ثابت
    وبينستبدل** كل مرّة — نسخة وحدة بتتحدّث، مش تاريخ بيتراكم.

    الملف الشخصي بيضلّ المصدر؛ هاي نسخة مقروءة للبحث بتتولّد منه.
    """
    try:
        from datetime import datetime, timezone

        from app.db import get_db

        db = get_db()
        coll_user = _coll()
        if db is None or coll_user is None:
            return
        user = coll_user.find_one({"_id": user_id}, {"onboarding": 1}) or {}
        ob = user.get("onboarding") or {}

        lines = []
        if str(ob.get("preferred_name") or "").strip():
            lines.append(("onboarding_name",
                          f"اسمه المفضّل: {str(ob['preferred_name']).strip()}"))
        interests = [str(i).strip() for i in (ob.get("interests") or []) if str(i).strip()]
        if interests:
            lines.append(("onboarding_interests", "اهتماماته: " + "، ".join(interests)))
        if str(ob.get("notes") or "").strip():
            lines.append(("onboarding_notes", f"عن نفسه: {str(ob['notes']).strip()}"))

        for key, text in lines:
            db["sandy_memories"].update_one(
                {"chat_id": user_id, "source_key": key},
                {"$set": {"chat_id": user_id, "user_id": user_id,
                          "label": "user_fact", "content": text,
                          "source_key": key,
                          "created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
    except Exception as exc:  # noqa: BLE001 — نسخة مساعدة، ما بتوقّف حفظ التعارف
        logger.debug("[UsersStore] onboarding mirror skipped: %s", exc)


def get_nudge_answers(user_id: str) -> Dict[str, Any]:
    """The user's stored daily-nudge question answers ({qid: answer}) — used to
    pick the next unanswered get-to-know-you question."""
    coll = _coll()
    if coll is None or not user_id:
        return {}
    doc = coll.find_one({"_id": user_id}, {"onboarding.nudge_answers": 1}) or {}
    return ((doc.get("onboarding") or {}).get("nudge_answers")) or {}


def record_nudge_answer(user_id: str, qid: str, answer: str) -> bool:
    """Save one daily-nudge question answer (feeds the evolving profile)."""
    coll = _coll()
    qid = (qid or "").strip()
    answer = (answer or "").strip()[:300]
    if coll is None or not user_id or not qid or not answer:
        return False
    res = coll.update_one(
        {"_id": user_id},
        {"$set": {f"onboarding.nudge_answers.{qid}": answer, "last_seen_at": _now()}},
    )
    return res.matched_count > 0


_DEFAULT_PERSONA: Dict[str, Any] = {"dialect": "palestinian", "custom_instructions": ""}


def get_persona(user_id: str) -> Dict[str, Any]:
    """The user's dialect + custom instructions, or the defaults (Palestinian
    dialect, no override) if unset or the store is unavailable."""
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
    """Save dialect and/or custom instructions. Pass ``""`` for
    ``custom_instructions`` to reset to the default persona."""
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
