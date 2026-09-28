"""Light text cleanup before the LLM sees a message; parsing is left to the model."""

import re

_ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_EASTERN_ARABIC_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def normalize_user_message(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    normalized = text.translate(_ARABIC_INDIC_DIGITS).translate(_EASTERN_ARABIC_DIGITS)
    normalized = normalized.replace("،", ",").replace("؟", "?").replace("ـ", "")
    return re.sub(r"\s+", " ", normalized).strip()
