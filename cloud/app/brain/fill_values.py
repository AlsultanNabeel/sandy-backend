"""What a fill may write and pick: only what he said (`features/browser_job`).

His values are read from his own words by code, never from the model's (`his_values`: his
messages of the conversation, and his name from his profile when he says «اسمي», «my name»):
what follows a field's name («الاسم: نبيل», «phone 0599…»), an e-mail address, a phone
number, and each word of his that is not a command («حطي»، «fill», «the form»).

Before any value is typed (`vet_type`), any box ticked or option picked (`vet_choose`), it is
checked against them: as he said it (a phone by its digits), never one that only looks like
it («Nabeel» for «نبيل», «Extra Large» for «large»); never a choice of his typed into a text
field («نبيل لارج», 4 Nov 2026: the size went into the name); never a value of one kind in a
field of another (an e-mail in the name). A choice may be named in the other script: «لارج»
picks «Large», by the letters both are said with (`_skeleton`). What is refused is asked of
him (`asked`), and the question before sending shows every field and which required one is
empty (`summary`).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from app.brain import lang

NOT_HIS, A_CHOICE, WRONG_FIELD = "not_his", "a_choice", "wrong_field"
NAME, EMAIL, PHONE, TEXT = "name", "email", "phone", "text"

_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d\s\-()]{5,}\d")
_CLAUSES = re.compile(r"[،,;\n؛]+")
_PAIR = re.compile(r"^\s*([^:：=]{1,30}?)\s*[:：=]\s*(.+?)\s*$")
_KEY = re.compile(
    r"(?:^|\s)(الاسم|اسم|الهاتف|هاتف|الجوال|جوال|الموبايل|موبايل|الرقم|رقم|الإيميل|الايميل|إيميل|ايميل|البريد|"
    r"الحجم|حجم|ملاحظات|name|e-?mail|phone|tel|telephone|mobile|number|size|notes?|comments?)\s+(.+)$", re.I)
_PARTS = re.compile(r"\s+(?:and|with|&|مع)\s+|\s+و(?=\S)", re.I)
# He names his own name: his profile's is his value.
_HIS_NAME = re.compile(r"اسمي|باسمي|بإسمي|إسمي|\bmy name\b", re.I)
# His words that ask, not values.
_FILLER = frozenset("""
حطي حط حطيلي عبي عبيلي عبيها املي امليلي اكتبي اكتب سجليني سجلي اعملي بدي بدك ابغى اريد لو سمحت من فضلك
النموذج نموذج الفورم فورم الصفحه صفحه على في ب من مع و او هاد هاي هالنموذج فيه فيها الي اللي اسمي باسمي
fill in out it the a an form page this that with my me please for on of to and or put enter use type sign up
""".split())
_FIELD_KINDS = ((EMAIL, re.compile(r"e-?mail|بريد|إيميل|ايميل", re.I)),
                (PHONE, re.compile(r"phone|\btel\b|mobile|هاتف|جوال|موبايل|رقم", re.I)),
                (NAME, re.compile(r"name|اسم", re.I)))
_TASHKEEL = re.compile(r"[ً-ْـ]")


def _norm(text: Any) -> str:
    s = _TASHKEEL.sub("", str(text or "")).lower()
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", s).strip(" .،,؛;:!?؟\"'«»()")


# The letters a word is said with, in either script: «لارج» and «Large» are «lrj».
_AR = {"ب": "b", "ت": "t", "ث": "t", "ج": "j", "ح": "h", "خ": "kh", "د": "d", "ذ": "z", "ر": "r", "ز": "z",
       "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "", "غ": "gh", "ف": "f", "ق": "k",
       "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "ة": "h", "ء": "", "ئ": "", "ؤ": "", "پ": "b",
       "چ": "sh", "ڤ": "v", "گ": "j"}
_LATIN = {"c": "k", "q": "k", "g": "j", "x": "ks", "p": "b", "v": "f", "w": "", "y": ""}


def _skeleton(text: str) -> str:
    out = []
    for ch in _norm(text):
        if ch in _AR:
            out.append(_AR[ch])
        elif "a" <= ch <= "z":
            out.append("" if ch in "aeiou" else _LATIN.get(ch, ch))
    s = "".join(out).replace("ch", "sh").replace("ck", "k")
    return re.sub(r"(.)\1+", r"\1", s)


def _kind_of_value(text: str, key: str = "") -> str:
    if _EMAIL.fullmatch(text.strip()):
        return EMAIL
    if _PHONE.fullmatch(text.strip()) and sum(c.isdigit() for c in text) >= 7:
        return PHONE
    for kind, words in _FIELD_KINDS:
        if key and words.search(key):
            return kind
    return TEXT


def _value(text: str, kind: str) -> Dict[str, str]:
    norm = re.sub(r"\D", "", text) if kind == PHONE else _norm(text)
    return {"text": text.strip(), "kind": kind, "norm": norm}


def his_values(said: Iterable[str], preferred_name: str = "") -> List[Dict[str, str]]:
    """The values in his own words (his messages), and his name when he names it."""
    out: List[Dict[str, str]] = []

    def add(text: str, kind: str) -> None:
        text = text.strip()
        if text and not any(v["text"] == text and v["kind"] == kind for v in out):
            out.append(_value(text, kind))

    for message in said:
        words = _URL.sub(" ", str(message or ""))
        if preferred_name and _HIS_NAME.search(words):
            add(preferred_name, NAME)
        for m in _EMAIL.finditer(words):
            add(m.group(0), EMAIL)
        for m in _PHONE.finditer(_EMAIL.sub(" ", words)):
            if sum(c.isdigit() for c in m.group(0)) >= 7:
                add(m.group(0), PHONE)
        for clause in _CLAUSES.split(words):
            pair = _PAIR.match(clause) or _KEY.search(clause)
            if pair:
                key, value = pair.group(1), pair.group(2)
                add(value, _kind_of_value(value, key))
                for part in _PARTS.split(value):
                    add(part, _kind_of_value(part, key))
            for token in re.split(r"[\s:：=]+", clause):
                word = token.strip(" .،,؛;:!?؟\"'«»()")
                if _norm(word).startswith("و") and len(word) > 3 and _norm(word[1:]) not in _FILLER:
                    word = word[1:]             # «ولارج»: «و» is «and»
                if len(word) >= 2 and _norm(word) not in _FILLER and not _EMAIL.search(word) \
                        and not any(c.isdigit() for c in word):
                    add(word, TEXT)
    return out


def _field_kind(field: Dict[str, Any]) -> str:
    kind = str(field.get("type") or "").lower()
    if kind == "email":
        return EMAIL
    if kind == "tel":
        return PHONE
    words = " ".join(str(field.get(k) or "") for k in ("label", "name", "id", "autocomplete"))
    for found, pattern in _FIELD_KINDS:
        if pattern.search(words):
            return found
    return TEXT


def _same(a: str, b: str) -> bool:
    """One choice: the same words, or the same letters in the other script."""
    if _norm(a) == _norm(b):
        return True
    sa, sb = _skeleton(a), _skeleton(b)
    return len(sa) >= 2 and sa == sb


def vet_type(values: List[Dict[str, str]], text: str, field: Dict[str, Any]) -> Optional[str]:
    """Why ``text`` may not be typed into ``field`` (None when it may)."""
    if not _norm(text):
        return None                       # clearing a field writes nothing of anyone's
    digits = re.sub(r"\D", "", text)
    matches = [v for v in values if v["norm"] == (digits if v["kind"] == PHONE else _norm(text))]
    if not matches:
        return NOT_HIS
    kind = _field_kind(field)
    if kind in (TEXT, NAME) and any(_same(text, c) for c in field.get("choices") or []):
        return A_CHOICE
    kinds = {v["kind"] for v in matches}
    if kind in (EMAIL, PHONE) and kind not in kinds:
        return WRONG_FIELD
    if kind in (TEXT, NAME) and kinds <= {EMAIL, PHONE}:
        return WRONG_FIELD
    return None


def vet_choose(values: List[Dict[str, str]], label: str, checked: bool) -> Optional[str]:
    """Why the option ``label`` may not be ticked or picked (None when it may). Unticking takes
    nothing of his."""
    if checked:
        return None
    return None if any(v["kind"] == TEXT and _same(v["text"], label) for v in values) else NOT_HIS


def summary(fields: List[Dict[str, Any]]) -> str:
    """Every field with its value, an empty one said, and a required empty one said so."""
    shown = []
    for f in fields:
        value = str(f.get("value") or "").strip()
        if not value:
            value = lang.say("fill_empty_required" if f.get("required") else "fill_empty")
        shown.append(f"{f.get('field') or '؟'}: {value}")
    return lang.say("sep").join(shown)


def asked(refused: List[Dict[str, str]]) -> str:
    """What she did not write, because he did not give it: asked of him."""
    names = list(dict.fromkeys(str(r.get("field") or "؟") for r in refused))
    return lang.say("fill_asked", fields=lang.say("sep").join(f"«{n}»" for n in names))
