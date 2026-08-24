import re
from typing import Any, Dict


from app.utils.nlp_normalizer import normalize_user_message
from app.agent.pending import create_pending_action, clear_pending_action


def _task_choice_index(text: str):
    value = normalize_user_message(str(text or "").strip()).lower()
    value = value.translate(
        str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    )
    value = (
        value.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
        .replace("ى", "ي")
    )
    value = " ".join(value.split())

    if not value:
        return None

    if value == "!":
        return 0

    if value.isdigit():
        return int(value) - 1

    first_words = {
        "اول",
        "الاول",
        "اولى",
        "الاولى",
        "اولي",
        "الاولي",
        "الاولاني",
        "الاولانية",
        "اولاني",
        "اولانية",
        "اول واحد",
        "اول وحده",
        "اول وحدة",
        "المهمة الاولى",
        "المهمه الاولى",
        "المهمة الاولي",
        "المهمه الاولي",
        "اول مهمة",
        "اول مهمه",
        "المهمة الاولانية",
        "المهمه الاولانيه",
    }
    second_words = {
        "ثاني",
        "الثاني",
        "ثانية",
        "الثانية",
        "تاني",
        "التاني",
        "تانية",
        "التانية",
        "ثاني مهمة",
        "تاني مهمة",
        "المهمة الثانية",
        "المهمه التانية",
    }

    third_words = {
        "ثالث",
        "الثالث",
        "ثالثة",
        "الثالثة",
        "تالت",
        "التالت",
        "تالتة",
        "التالتة",
        "ثالث مهمة",
        "تالت مهمة",
        "المهمة الثالثة",
        "المهمه التالتة",
    }

    fourth_words = {
        "رابع",
        "الرابع",
        "رابعة",
        "الرابعة",
        "رابع مهمة",
        "المهمة الرابعة",
        "المهمه الرابعة",
    }

    fifth_words = {
        "خامس",
        "الخامس",
        "خامسة",
        "الخامسة",
        "خامس مهمة",
        "المهمة الخامسة",
        "المهمه الخامسة",
    }

    groups = [first_words, second_words, third_words, fourth_words, fifth_words]

    for index, words in enumerate(groups):
        if value in words:
            return index

    if "رقم " in value:
        maybe_number = value.split("رقم ", 1)[1].strip()
        if maybe_number.isdigit():
            return int(maybe_number) - 1

    return None


def _task_choice_pair_indexes(text: str, choices_count: int):
    value = normalize_user_message(str(text or "").strip()).lower()
    value = value.translate(
        str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    )
    value = (
        value.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
    )
    value = " ".join(value.split())

    pair_words = {
        "التنتين",
        "التنين",
        "الاتنين",
        "الثنتين",
        "الاثنين",
        "اتنين",
        "اثنين",
        "التنين مع بعض",
        "الاتنين مع بعض",
        "التنتين مع بعض",
    }

    if choices_count == 2 and value in pair_words:
        return [0, 1]

    return None


def _has_visible_task_note(task: Dict[str, Any]) -> bool:
    notes = str(task.get("notes", "") or "").strip()
    if not notes:
        return False

    visible_lines = [
        line.strip()
        for line in notes.splitlines()
        if line.strip()
        and not (line.strip().startswith("[SANDY_") and line.strip().endswith("]"))
    ]

    return bool(visible_lines)


# ── Confirmation / cancellation ──────────────────────────────────────────────
# ONE normalized resolver, shared by the router (routing a reply to pending_node)
# AND the pending dispatcher (deciding confirm/reject). The two used to keep
# separate, divergent word lists that didn't normalize Arabic — so a reply like
# "اه صح" / "آه" / "اه 👍" matched neither, the pending was dropped, and the
# plain-chat fallback hallucinated "حذفت" without deleting. Keeping the matching
# here, normalized and in one place, is the fix.

# Broad set for an exact single-word reply.
_AFFIRM_EXACT = {
    "اه", "ايه", "اي", "نعم", "ايوه", "ايوا", "اكيد", "تمام", "تمم", "ماشي",
    "اوك", "اوكي", "حسنا", "صح", "احذف", "احذفها", "احذفهم", "نفذ", "اعمل",
    "yes", "ok", "okay", "sure", "yep", "yup", "confirmed", "y",
}
# Conservative leads allowed to head a short multi-word affirmative ("اه صح",
# "اه احذفها") — ambiguous tokens like "اي"/"ايه" are NOT here, so they can only
# confirm as a bare single word, never as the head of a phrase.
_AFFIRM_LEAD = {
    "اه", "نعم", "ايوه", "ايوا", "اكيد", "تمام", "ماشي", "اوك", "اوكي",
    "yes", "ok", "okay", "sure", "confirmed",
}
_CANCEL_EXACT = {
    "لا", "لاء", "الغ", "الغاء", "مش", "خلص", "بطل", "بلاش",
    "no", "cancel", "nope", "dont", "stop", "nah", "n",
}
_CANCEL_SUB = (
    "لا تحذف", "مش الان", "انسي", "وقف", "وقفي",
    "الغي", "الغيها", "الغيهم", "لا تضيف",
)


def _norm_confirm(text: str) -> str:
    """Aggressive normalization for yes/no matching: fold digits, punctuation,
    tatweel, emoji, and Arabic letter variants (alef/hamza/ta-marbuta/alef-
    maqsura) so 'آه'، 'اه.'، 'اه 👍'، 'اه صح' reduce to comparable tokens."""
    v = normalize_user_message(str(text or "")).lower()
    for a, b in (
        ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"),
        ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي"),
    ):
        v = v.replace(a, b)
    v = re.sub(r"[^\w\s]", " ", v)  # drop remaining punctuation/symbols
    return " ".join(v.split())


def _is_quick_confirmation(text: str) -> bool:
    """True for a short affirmative reply to a pending confirmation — a bare
    'اه/نعم/تمام/ok', an emoji-tailed 'اه 👍', or a short multi-word affirmative
    whose first word is an unambiguous yes ('اه صح', 'اه احذفها')."""
    v = _norm_confirm(text)
    if not v:
        return False
    words = v.split()
    if len(words) > 4:
        return False
    if v in _AFFIRM_EXACT:
        return True
    return len(words) >= 2 and words[0] in _AFFIRM_LEAD


def is_cancellation(text: str) -> bool:
    """True when the user wants to cancel/reject a pending action. Same
    normalization as _is_quick_confirmation, and callers check this FIRST so a
    reply like 'اه بس لا' resolves to cancel, not confirm. Bounded to short
    replies so a trigger word buried in a narrative can't read as a cancel."""
    v = _norm_confirm(text)
    if not v or len(v.split()) > 4:
        return False
    # Any standalone negation token (not substring — so it won't fire inside a
    # word) wins; erring toward "cancel" on a mixed reply is the safe bias for a
    # destructive pending. Token match keeps it precise.
    if any(w in _CANCEL_EXACT for w in v.split()):
        return True
    return any(s in v for s in _CANCEL_SUB)


def _handle_modify_response(
    *,
    user_message: str,
    pending: Dict[str, Any],
    pending_type: str,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    save_session_fn,
) -> Dict[str, Any]:
    """User wants to fix something. Ask for the right field based on pending_type."""

    if pending_type == "reminder":
        # Ask for the new date/time.
        session["pending_action"] = create_pending_action(
            {
                "type": "reminder",
                "action": "awaiting_corrected_date",
                "original_action": pending.get("action", ""),
                "original_data": pending,
                "correction_step": 1,
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)

        return {
            "handled": True,
            "reply": "تمام، قول لي التاريخ والساعة الصحيحة للتذكير؟\nمثلاً: غدا عند الساعة 3 أو الجمعة عند 9 صباح",
        }

    elif pending_type == "task":
        # Ask which field to change.
        session["pending_action"] = create_pending_action(
            {
                "type": "task",
                "action": "awaiting_field_to_modify",
                "original_action": pending.get("action", ""),
                "original_data": pending,
                "correction_step": 1,
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)

        task_text = pending.get("text", "المهمة")
        return {
            "handled": True,
            "reply": f"متأكد، بدك تعدّل شنو من المهمة؟\nالمهمة: {task_text}\n\nبدك تعدّل: الاسم، التاريخ، الملاحظة، أو الأولوية؟",
        }

    elif pending_type == "calendar":
        # Ask which field to change.
        session["pending_action"] = create_pending_action(
            {
                "type": "calendar",
                "action": "awaiting_field_to_modify",
                "original_action": pending.get("action", ""),
                "original_data": pending,
                "correction_step": 1,
            }
        )
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)

        event_title = pending.get("title", "الحدث")
        return {
            "handled": True,
            "reply": f"متأكد، بدك تعدّل شنو من الحدث؟\nالحدث: {event_title}\n\nبدك تعدّل: الوقت، التاريخ، الموقع، أو الوصف؟",
        }

    else:
        clear_pending_action(session)
        save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
        return {
            "handled": True, "ok": False,
            "reply": "ما قدرت أكمل التعديل. جرّب من جديد.",
        }
