"""Who is on the other end of this request.

The active profile lives in a ContextVar; ``current_user_id()`` reads the tenant
from it and every scoped store filters on that. Also here: how to address the
speaker (gender, name) and the one-time owner-identity reconciliation at boot.

A JSON/Mongo "per-chat profile store" (find/save/ensure_user_profile and its
normaliser) sat in this module after the Telegram transport that used it was
removed — called from nowhere but its own tests, and the last place that still
encoded "tenant #1 is special". It is gone; profiles come from the JWT through
``build_user_profile``.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# The owner's legacy identities, read by `reconcile_owner_identity` and the
# voice path's owner lookup.
OWNER_CHAT_ID = (os.getenv("OWNER_CHAT_ID", "") or "").strip()
LEGACY_OWNER_CHAT_ID = (os.getenv("SANDY_USER_CHAT_ID", "") or "").strip()
# The owner's clean product tenant id (his sandy_users uuid after the Phase 1
# migration). A stale value here is folded onto the canonical id at boot.
OWNER_TENANT_ID = (os.getenv("OWNER_TENANT_ID", "") or "").strip()

# The active tenant profile for the current request/task. A ContextVar (not
# threading.local) so the identity propagates correctly across asyncio tasks and
# any executor that copies the context, while still isolating per-thread by
# default: a pool thread that never enters active_user_profile_context reads the
# default (None) — exactly as the old thread-local did — so background work still
# fails closed (current_user_id() is None → stores read/write nothing).
_ACTIVE_PROFILE: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "sandy_active_user_profile", default=None
)

def set_active_user_profile(profile: Optional[Dict[str, Any]]) -> None:
    _ACTIVE_PROFILE.set(profile)


def get_active_user_profile() -> Optional[Dict[str, Any]]:
    profile = _ACTIVE_PROFILE.get()
    return profile if isinstance(profile, dict) else None


def current_user_id() -> Optional[str]:
    """The authenticated user's stable id for the current request/context.

    Backed by the active profile's identity (its ``chat_id`` is the user_id on
    web). Returns None when no profile is active.
    Stores scope every read/write to this id so each user only sees their data.
    """
    profile = get_active_user_profile()
    if not profile:
        return None
    uid = profile.get("chat_id")
    return str(uid) if uid not in (None, "") else None


@contextmanager
def active_user_profile_context(profile: Optional[Dict[str, Any]]):
    # Token-based reset restores the exact prior value (correct under nesting), and
    # ContextVar keeps that restore scoped to this task/thread.
    token = _ACTIVE_PROFILE.set(profile)
    try:
        yield
    finally:
        _ACTIVE_PROFILE.reset(token)


def address_instruction(profile: Optional[Dict[str, Any]] = None) -> str:
    """Arabic line telling Sandy which grammatical gender to address the speaker
    with.

    Masculine is the default because Arabic forces a choice, **not** because the
    speaker is a particular person: this used to read «المالك نبيل افتراضياً»,
    so every woman who used the product was told she was the owner by default.

    **The default stays conditional on purpose.** `gender` is read from the
    active profile and no production path sets it today, so the escape hatch
    that matters is the one inside the sentence: the model is told to switch the
    moment it learns otherwise. A flat masculine assertion would leave a female
    customer's robot with no way out at all — worse than the guess it replaced.
    """
    if profile is None:
        profile = get_active_user_profile()
    gender = str((profile or {}).get("gender", "") or "").strip().lower()
    if gender == "female":
        return "المتحدثة معك أنثى — خاطبيها بصيغة المؤنث."
    return (
        "الافتراضي مذكر لحد ما تتأكدي — خاطبيه بصيغة المذكر؛ وإذا بان إنّ "
        "المتحدثة أنثى، خاطبيها بصيغة المؤنث من هديك اللحظة."
    )


def active_profile_is_guest() -> bool:
    """True for an unauthenticated visitor (chat-only). Every authenticated user
    — owner included — has ``permissions == "all"`` and is NOT a guest, so they
    get full CRUD on THEIR own tenant data. Data isolation is enforced by the
    per-user ``current_user_id()`` scoping, not by an owner check."""
    profile = get_active_user_profile()
    if not profile:
        return False
    permissions = (
        str(profile.get("permissions", "chat-only") or "chat-only").strip().lower()
    )
    return permissions != "all"


def build_user_profile(claims: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the active-user profile for an authenticated web/app request.

    The profile's ``chat_id`` is the caller's stable ``user_id`` from their JWT,
    which is what ``current_user_id()`` resolves to — so every feature store
    read/write inside ``active_user_profile_context(...)`` is scoped to THIS
    user. The owner is just an authenticated user (tenant #1): every
    authenticated caller (owner or regular user) gets ``permissions == "all"``
    and so full CRUD on THEIR own data; only a true guest is ``chat-only``.
    There is no owner-id fallback — a token without a ``user_id`` yields an
    empty scope, so nobody can ever inherit another user's data.

    Shared by the web agent and the REST tab endpoints so the per-user wiring
    lives in exactly one place.
    """
    claims = claims or {}
    is_guest = claims.get("role", "guest") == "guest"
    user_id = str(claims.get("user_id") or "")
    return {
        "chat_id": user_id,
        "name": "",
        "relation": "guest" if is_guest else "user",
        "tone": "casual",
        "permissions": "chat-only" if is_guest else "all",
    }


def resolve_display_name(user_id: str | None = None, mongo_db=None, default: str = "") -> str:
    """Best-effort display name for the active/given user.

    Order: onboarding preferred_name (sandy_users) → default.
    Crash-safe: returns `default` if the store is unavailable or unset.
    """
    if not user_id:
        user_id = current_user_id()
    if not user_id:
        return default
    try:
        from app.features import users_store

        user = users_store.get_user(user_id)
        name = str((user or {}).get("onboarding", {}).get("preferred_name", "") or "").strip()
        return name or default
    except Exception as exc:
        # A missing name is expected for guests — log quietly and degrade (C1).
        logger.debug("[user_profiles] resolve_display_name failed: %s", exc)
        return default


# What `speaker_label` returns when nobody has told us a name. Callers that
# build a *discriminating* sentence — "this is not X", "even if he claims to be
# X" — must branch on it rather than substitute it, or they end up asserting
# that the speaker is not "the user".
HAS_NO_NAME = "المستخدم"


def speaker_label(user_id: str | None = None, mongo_db=None) -> str:
    """What to call the person in front of Sandy, in a prompt or a transcript.

    Every site that needed this had the owner's name typed into it — the live
    voice prompt, the speaker-verification note, the transcript labels, the
    morning brief. So a customer who had just typed «سامي» into first-run setup
    was told, by their own robot, that they were talking to somebody else.

    `المستخدم` when no name is known. That is the honest answer; another
    person's name is not, and a blank is worse than either — a prompt reading
    "you are in a voice conversation with " invites the model to fill the gap.
    """
    return resolve_display_name(user_id, mongo_db, default=HAS_NO_NAME)


def reconcile_owner_identity(mongo_db) -> None:
    """One-time-per-boot: merge durable memory still tagged with one of the
    owner's legacy identities (``OWNER_CHAT_ID`` / ``SANDY_USER_CHAT_ID`` / a
    stale ``OWNER_TENANT_ID``), or with none at all, onto his canonical
    ``users_store`` uuid — the id every REST/text-chat request resolves via
    ``current_user_id()``. Idempotent, and only ever touches rows already
    tagged as the owner's (or untagged pre-isolation docs) — never another
    tenant's.

    ``api/voice_ws/`` used to key STM/persona/facts off the legacy env-var
    ids directly (there's no active profile there to derive the canonical id
    from), so without this reconciliation his voice and text-chat memories
    silently lived in different tenants.
    """
    if mongo_db is None:
        return
    try:
        from app.features import users_store

        canonical = users_store.get_or_create_owner()
    except Exception as exc:
        logger.warning("[user_profiles] owner identity reconcile skipped: %s", exc)
        return
    if not canonical:
        return

    legacy_ids = [
        i for i in {OWNER_CHAT_ID, LEGACY_OWNER_CHAT_ID, OWNER_TENANT_ID}
        if i and i != canonical
    ]

    for coll_name, field in (
        ("sandy_memories", "chat_id"),
        ("sandy_facts", "chat_id"),
        ("sandy_conversations", "chat_id"),
        ("memory", "user_id"),
    ):
        or_terms = [{field: {"$exists": False}}]
        if legacy_ids:
            or_terms.append({field: {"$in": legacy_ids}})
        try:
            result = mongo_db[coll_name].update_many(
                {"$or": or_terms},
                {"$set": {field: canonical}},
            )
            if result.modified_count:
                logger.info(
                    "[user_profiles] reconciled %d doc(s) in %s onto the owner's tenant id",
                    result.modified_count, coll_name,
                )
        except Exception as exc:
            logger.warning("[user_profiles] reconcile failed for %s: %s", coll_name, exc)
