"""Per-chat profile storage for Sandy."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional, Tuple

from app.utils.files import read_json_file, write_json_file

logger = logging.getLogger(__name__)


def _parse_id_set(raw: str) -> set:
    return {s.strip() for s in (raw or "").split(",") if s.strip()}


_OWNER_IDS: set = _parse_id_set(os.getenv("OWNER_CHAT_ID", "")) | _parse_id_set(
    os.getenv("SANDY_USER_CHAT_ID", "")
)

# Keep these for any external code that still imports them directly
OWNER_CHAT_ID = (os.getenv("OWNER_CHAT_ID", "") or "").strip()
LEGACY_OWNER_CHAT_ID = (os.getenv("SANDY_USER_CHAT_ID", "") or "").strip()
# The owner's clean product tenant id (his sandy_users uuid after the Phase 1
# migration). /api/auth now logs him in under THIS id, so the transitional
# device gates (robot/room) must recognise it as the owner too.
OWNER_TENANT_ID = (os.getenv("OWNER_TENANT_ID", "") or "").strip()

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "memory"
USER_PROFILES_FILE = DATA_DIR / "user_profiles.json"

# The active tenant profile for the current request/task. A ContextVar (not
# threading.local) so the identity propagates correctly across asyncio tasks and
# any executor that copies the context, while still isolating per-thread by
# default: a pool thread that never enters active_user_profile_context reads the
# default (None) — exactly as the old thread-local did — so background work still
# fails closed (current_user_id() is None → stores read/write nothing).
_ACTIVE_PROFILE: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "sandy_active_user_profile", default=None
)

DEFAULT_TONE_BY_RELATION = {
    "owner": "casual",
    "user": "casual",
    "family": "gentle",
    "guest": "formal",
}

DEFAULT_PERMISSIONS_BY_RELATION = {
    # An authenticated tenant, owner or not, has full rights over their OWN
    # data — isolation is `current_user_id()` scoping, never a relation check.
    "owner": "all",
    "user": "all",
    "family": "chat-only",
    "guest": "chat-only",
}

SENSITIVE_KEYWORDS = (
    "task",
    "tasks",
    "مهام",
    "مهمة",
    "calendar",
    "تقويم",
    "موعد",
    "مواعيد",
    "ذاكرة",
    "memory",
    "ذكرياتي",
    "تذكر",
    "ذكّر",
    "ذكرني",
)


def _chat_key(chat_id: Any) -> str:
    return str(chat_id).strip()


def is_owner_chat_id(chat_id: Any) -> bool:
    chat_key = _chat_key(chat_id)
    if not chat_key:
        return False
    return chat_key in (
        _parse_id_set(OWNER_CHAT_ID)
        | _parse_id_set(LEGACY_OWNER_CHAT_ID)
        | _parse_id_set(OWNER_TENANT_ID)
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


def _normalize_relation(value: str) -> str:
    relation = str(value or "guest").strip().lower()
    # `build_user_profile` has emitted "user" for every authenticated caller
    # since the multi-tenant migration and this never learned the word, so it
    # round-tripped to "guest" — which forces permissions to chat-only and would
    # fire the privacy refusal at a paying customer.
    return relation if relation in {"owner", "user", "family", "guest"} else "guest"


def _normalize_profile(
    chat_id: Any, profile: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    relation = "owner" if is_owner_chat_id(chat_id) else "guest"
    normalized = {
        "chat_id": _chat_key(chat_id),
        "name": "",
        "relation": relation,
        "tone": DEFAULT_TONE_BY_RELATION[relation],
        "permissions": DEFAULT_PERMISSIONS_BY_RELATION[relation],
        "gender": "",
    }

    if isinstance(profile, dict):
        normalized["name"] = str(profile.get("name", "") or "").strip()
        normalized["relation"] = _normalize_relation(profile.get("relation", relation))
        normalized["tone"] = str(profile.get("tone", "") or "").strip().lower()
        normalized["permissions"] = (
            str(profile.get("permissions", "") or "").strip().lower()
        )
        _g = str(profile.get("gender", "") or "").strip().lower()
        normalized["gender"] = _g if _g in {"male", "female"} else ""

    if is_owner_chat_id(chat_id):
        normalized["relation"] = "owner"
        normalized["tone"] = "casual"
        normalized["permissions"] = "all"
        normalized["gender"] = "male"  # the owner's own profile, set by him
    else:
        # **Not "anyone who is not the owner is chat-only".** That was the rule
        # for one person's house; in a product it refuses a paying customer
        # their own data. Rights follow the relation, and the isolation that
        # matters is `current_user_id()` scoping — see `active_profile_is_guest`,
        # which every store already consults.
        normalized["relation"] = _normalize_relation(normalized["relation"])
        normalized["tone"] = (
            normalized["tone"]
            if normalized["tone"] in {"casual", "gentle", "formal"}
            else DEFAULT_TONE_BY_RELATION[normalized["relation"]]
        )
        # **حدّ أعلى، مش قيمة افتراضية.** التراجع للافتراضي بيصلح القيم
        # المكسورة بس، وبيخلّي قاموس المتصل يغلب العلاقة: ضيف بصلاحيات «all»
        # كان مستحيل بناءً، وصار مقبول — و`active_profile_is_guest` بتقرا
        # الصلاحيات وحدها، يعني هيك ملف بيعدّي كل بوابات الضيف بالنظام.
        allowed = DEFAULT_PERMISSIONS_BY_RELATION[normalized["relation"]]
        if allowed != "all" or normalized["permissions"] not in {"all", "chat-only"}:
            normalized["permissions"] = allowed

    return normalized


def _default_profile(chat_id: Any) -> Dict[str, Any]:
    return _normalize_profile(chat_id, None)


def _read_json_profiles() -> Dict[str, Dict[str, Any]]:
    raw = read_json_file(USER_PROFILES_FILE, {})
    return raw if isinstance(raw, dict) else {}


def _write_json_profiles(profiles: Dict[str, Dict[str, Any]]) -> bool:
    return write_json_file(USER_PROFILES_FILE, profiles)


def find_user_profile(chat_id: Any, mongo_db: Any = None) -> Optional[Dict[str, Any]]:
    chat_key = _chat_key(chat_id)
    if not chat_key:
        return None

    if is_owner_chat_id(chat_key):
        return _default_profile(chat_key)

    if mongo_db is not None:
        try:
            doc = mongo_db["user_profiles"].find_one({"_id": chat_key})
            if doc:
                doc = dict(doc)
                doc.pop("_id", None)
                return _normalize_profile(chat_key, doc)
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

    profiles = _read_json_profiles()
    profile = profiles.get(chat_key)
    if profile:
        return _normalize_profile(chat_key, profile)
    return None


def save_user_profile(
    chat_id: Any, profile: Dict[str, Any], mongo_db: Any = None
) -> Dict[str, Any]:
    chat_key = _chat_key(chat_id)
    normalized = _normalize_profile(chat_id, profile)

    if mongo_db is not None:
        try:
            mongo_db["user_profiles"].replace_one(
                {"_id": chat_key},
                {**normalized, "_id": chat_key},
                upsert=True,
            )
            return normalized
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

    profiles = _read_json_profiles()
    profiles[chat_key] = normalized
    _write_json_profiles(profiles)
    return normalized


def ensure_user_profile(
    chat_id: Any, mongo_db: Any = None
) -> Tuple[Dict[str, Any], bool]:
    existing = find_user_profile(chat_id, mongo_db=mongo_db)
    if existing is not None:
        return existing, False
    created = _default_profile(chat_id)
    return save_user_profile(chat_id, created, mongo_db=mongo_db), True


def update_user_profile(
    chat_id: Any, updates: Dict[str, Any], mongo_db: Any = None
) -> Dict[str, Any]:
    profile, _ = ensure_user_profile(chat_id, mongo_db=mongo_db)
    merged = {**profile, **(updates or {})}
    return save_user_profile(chat_id, merged, mongo_db=mongo_db)


def extract_profile_name(message_text: str) -> str:
    text = str(message_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:اسمي|أنا اسمي|انا اسمي|اسمي هو|أنا هو|انا هو|my name is)\s*[:=\-–]?\s*(.+)$",
        r"^(?:أنا|انا)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate and len(candidate.split()) <= 3 and len(candidate) <= 40:
                return candidate

    words = text.split()
    if len(words) == 1 and len(text) <= 30 and not any(ch in text for ch in "؟?!.،,"):
        return text

    return ""


def is_sensitive_request(message_text: str) -> bool:
    text = str(message_text or "").lower()
    for keyword in SENSITIVE_KEYWORDS:
        # Latin keywords (task/email/...) get word-boundary matching so they don't
        # false-fire inside longer words. Arabic keywords keep substring matching:
        # Arabic word boundaries are unreliable, and this is a safety gate where we
        # deliberately err toward over-blocking guests.
        if keyword.isascii():
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                return True
        elif keyword in text:
            return True
    return False


def build_user_profile_prompt_sections(
    profile: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    if not profile:
        return {"user_profile_block": "", "user_profile_priority_line": ""}

    normalized = _normalize_profile(profile.get("chat_id", ""), profile)
    tone_text = {
        "casual": "ردّي بأسلوب قريب وخفيف ومباشر، مع ألفاظ مألوفة بدون تكلف.",
        "gentle": "ردّي بلطف وهدوء، مع احترام واضح ولمسة ودّية.",
        "formal": "ردّي بصياغة مهذبة ورسمية ومختصرة.",
    }[normalized["tone"]]

    profile_block = (
        "\n👤 ملف المستخدم الحالي:\n"
        f"- الاسم: {normalized['name'] or 'غير معروف'}\n"
        f"- العلاقة: {normalized['relation']}\n"
        f"- النبرة: {normalized['tone']}\n"
        f"- الصلاحيات: {normalized['permissions']}\n"
        f"- توجيه النبرة: {tone_text}\n"
    )

    privacy_line = ""
    if normalized["permissions"] != "all":
        privacy_line = (
            "\n🔒 هذا الحساب chat-only: لا تنفذي أو تذكري أي تفاصيل من المهام أو التقويم أو البريد أو الذاكرة. "
            "إذا طُلب شيء من هذه المجالات، ارجعي فقط إلى: هذا خاص بصاحب الحساب 😊\n"
        )

    return {
        "user_profile_block": profile_block,
        "user_profile_priority_line": privacy_line,
    }


def is_sensitive_domain_request(message_text: str) -> bool:
    # Public alias kept for callers and tests; the canonical
    # implementation is is_sensitive_request.
    return is_sensitive_request(message_text)


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

    ``api/voice_ws.py`` used to key STM/persona/facts off the legacy env-var
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
