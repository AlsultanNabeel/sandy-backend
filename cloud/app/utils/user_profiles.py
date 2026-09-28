"""Who is on the other end of this request.

The active profile lives in a ContextVar; ``current_user_id()`` is the tenant
every scoped store filters on. Also: how to address the speaker, and the
boot-time owner-identity reconciliation.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# The owner's legacy identities, folded onto his canonical id at boot.
OWNER_CHAT_ID = (os.getenv("OWNER_CHAT_ID", "") or "").strip()
LEGACY_OWNER_CHAT_ID = (os.getenv("SANDY_USER_CHAT_ID", "") or "").strip()
OWNER_TENANT_ID = (os.getenv("OWNER_TENANT_ID", "") or "").strip()

# A context with no profile set reads None, so stores fail closed.
_ACTIVE_PROFILE: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "sandy_active_user_profile", default=None
)

def set_active_user_profile(profile: Optional[Dict[str, Any]]) -> None:
    _ACTIVE_PROFILE.set(profile)


def get_active_user_profile() -> Optional[Dict[str, Any]]:
    profile = _ACTIVE_PROFILE.get()
    return profile if isinstance(profile, dict) else None


def current_user_id() -> Optional[str]:
    """The tenant id every scoped store filters on; None with no active profile."""
    profile = get_active_user_profile()
    if not profile:
        return None
    uid = profile.get("chat_id")
    return str(uid) if uid not in (None, "") else None


@contextmanager
def active_user_profile_context(profile: Optional[Dict[str, Any]]):
    token = _ACTIVE_PROFILE.set(profile)
    try:
        yield
    finally:
        _ACTIVE_PROFILE.reset(token)


def address_instruction(profile: Optional[Dict[str, Any]] = None) -> str:
    """Arabic line telling Sandy which grammatical gender to use for the speaker.

    The masculine default stays conditional so the model can switch once it learns otherwise.
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
    """True for an unauthenticated (chat-only) visitor."""
    profile = get_active_user_profile()
    if not profile:
        return False
    permissions = (
        str(profile.get("permissions", "chat-only") or "chat-only").strip().lower()
    )
    return permissions != "all"


def build_user_profile(claims: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Active-user profile from JWT claims; ``chat_id`` is the JWT user_id.

    No owner fallback: a token without a user_id gets an empty scope.
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


def resolve_display_name(user_id: str | None = None, default: str = "") -> str:
    """Onboarding preferred_name for the given/active user, else ``default``."""
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
        logger.debug("[user_profiles] resolve_display_name failed: %s", exc)
        return default


# Callers building "this is not X" sentences must branch on this, not substitute it.
HAS_NO_NAME = "المستخدم"


def speaker_label(user_id: str | None = None) -> str:
    """Name for the speaker in prompts/transcripts; `المستخدم` when unknown (never blank)."""
    return resolve_display_name(user_id, default=HAS_NO_NAME)


def reconcile_owner_identity(mongo_db) -> None:
    """Boot-time, idempotent: move memory tagged with the owner's legacy ids (or untagged) onto his canonical uuid.

    Never touches another tenant's rows.
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
