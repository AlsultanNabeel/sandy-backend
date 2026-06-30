"""Per-chat profile storage for Sandy."""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from contextlib import contextmanager
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
_ACTIVE_PROFILE_STATE = threading.local()

DEFAULT_TONE_BY_RELATION = {
    "owner": "casual",
    "family": "gentle",
    "guest": "formal",
}

DEFAULT_PERMISSIONS_BY_RELATION = {
    "owner": "all",
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
    _ACTIVE_PROFILE_STATE.profile = profile


def get_active_user_profile() -> Optional[Dict[str, Any]]:
    profile = getattr(_ACTIVE_PROFILE_STATE, "profile", None)
    return profile if isinstance(profile, dict) else None


def current_user_id() -> Optional[str]:
    """The authenticated user's stable id for the current request/context.

    Backed by the active profile's identity (its ``chat_id`` is the user_id on
    web, or the chat id on Telegram). Returns None when no profile is active.
    Stores scope every read/write to this id so each user only sees their data.
    """
    profile = get_active_user_profile()
    if not profile:
        return None
    uid = profile.get("chat_id")
    return str(uid) if uid not in (None, "") else None


@contextmanager
def active_user_profile_context(profile: Optional[Dict[str, Any]]):
    previous = get_active_user_profile()
    set_active_user_profile(profile)
    try:
        yield
    finally:
        set_active_user_profile(previous)


def address_instruction(profile: Optional[Dict[str, Any]] = None) -> str:
    """Arabic line telling Sandy which grammatical gender to address the current
    speaker with. The default speaker is the owner (male), so anything that
    isn't an explicitly-female profile resolves to masculine."""
    if profile is None:
        profile = get_active_user_profile()
    gender = str((profile or {}).get("gender", "") or "").strip().lower()
    if gender == "female":
        return "المتحدثة معك أنثى — خاطبيها بصيغة المؤنث."
    return (
        "المتحدث معك ذكر (المالك نبيل افتراضياً حتى يتعرّف على ضيف) — "
        "خاطبيه بصيغة المذكر."
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
    return relation if relation in {"owner", "family", "guest"} else "guest"


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
        normalized["gender"] = "male"  # the owner is male — the default speaker
    else:
        normalized["relation"] = _normalize_relation(normalized["relation"])
        normalized["tone"] = (
            normalized["tone"]
            if normalized["tone"] in {"casual", "gentle", "formal"}
            else DEFAULT_TONE_BY_RELATION[normalized["relation"]]
        )
        normalized["permissions"] = "chat-only"

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
            pass

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
            pass

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
            "إذا طُلب شيء من هذه المجالات، ارجعي فقط إلى: هذا خاص بنبيل 😊\n"
        )

    return {
        "user_profile_block": profile_block,
        "user_profile_priority_line": privacy_line,
    }


def is_sensitive_domain_request(message_text: str) -> bool:
    # Public alias kept for callers (telegram_handlers, tests); the canonical
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
