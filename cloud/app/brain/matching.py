"""Find one row by what the user called it ("delete the gym task").

Exact, then contained, then fuzzy >= 0.72, on a normaliser that folds Arabic
letter variants, diacritics, digits and a leading «ال», applied to any block row
that has ``text``.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List

FUZZY = 0.72

# Words that name the row's type rather than the row ("delete the task gym").
_FILLER = {"مهمه", "المهمه", "تاسك", "task"}


def match_key(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"),
                 ("ؤ", "و"), ("ئ", "ي"), ("ى", "ي"), ("ة", "ه")):
        text = text.replace(a, b)
    text = re.sub(r"[^\w؀-ۿ]+", " ", text)
    tokens = []
    for token in text.split():
        if token in _FILLER:
            continue
        if token.startswith("ال") and len(token) > 3:
            token = token[2:]
        tokens.append(token)
    return " ".join(tokens)


def match_score(a: str, b: str) -> float:
    return SequenceMatcher(None, match_key(a), match_key(b)).ratio()


def match_rows(reference: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``{"status": matched|ambiguous|not_found|missing, "row", "matches"}``."""
    ref = match_key(reference)
    if not ref:
        return {"status": "missing", "row": None, "matches": []}
    ladder = (
        lambda r: match_key(r.get("text", "")) == ref,
        lambda r: ref in match_key(r.get("text", "")),
        lambda r: match_score(ref, r.get("text", "")) >= FUZZY,
    )
    for test in ladder:
        hits = [r for r in rows if test(r)]
        if len(hits) == 1:
            return {"status": "matched", "row": hits[0], "matches": hits}
        if hits:
            return {"status": "ambiguous", "row": None, "matches": hits}
    return {"status": "not_found", "row": None, "matches": []}
