"""«اشتريت الحليب»: what was bought comes off the shopping list, by the code, every time.

Before the model answers, a line that says something was bought is matched against the
open shopping items: a match is ticked done, or, when fewer were bought than the item
asks for («جبت ٢ بيض» of six), its quantity goes down. The model is told what was done,
logs the expense if a price was said, and never adds what was bought to the list.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.blocks import items

BOUGHT = re.compile(r"(?:^|\s)(?:و?(?:اشتريت|اشترينا|شريت|شرينا|جبت|جبنا|جيبت))(?:\s|$)|\b(?:bought|got|picked up)\b",
                    re.IGNORECASE)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_MARKS = re.compile(r"[ً-ْـ]")


def said_bought(message: str) -> bool:
    return bool(BOUGHT.search(message or ""))


def _norm(word: str) -> str:
    w = _MARKS.sub("", word.lower())
    w = w.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    for prefix in ("وال", "بال", "ال", "و"):
        if w.startswith(prefix) and len(w) - len(prefix) >= 2:
            w = w[len(prefix):]
            break
    return w


def _words(text: str) -> List[str]:
    return [_norm(w) for w in re.findall(r"\w+", (text or "").translate(_DIGITS))]


def _count_before(words: List[str], at: int) -> Optional[float]:
    """A number just before the item («2 بيض», «٣ علب حليب»)."""
    for w in words[max(0, at - 2):at]:
        if w.replace(".", "", 1).isdigit():
            return float(w)
    return None


def apply(message: str) -> List[Dict[str, Any]]:
    """Tick off (or lessen) the open shopping items this line says were bought.
    [{"id", "text", "done": bool, "left": qty or None}] — empty when nothing matched."""
    if not said_bought(message):
        return []
    said = _words(message)
    done: List[Dict[str, Any]] = []
    for item in items.list_items("shopping", done=False):
        name = _words(item.get("text", ""))
        if not name:
            continue
        at = next((i for i in range(len(said) - len(name) + 1) if said[i:i + len(name)] == name), None)
        if at is None:
            continue
        data = dict(item.get("data") or {})
        wanted = data.get("qty")
        got = _count_before(said, at)
        if isinstance(wanted, (int, float)) and got is not None and got < wanted:
            data["qty"] = wanted - got
            items.update(item["id"], data=data)
            done.append({"id": item["id"], "text": item["text"], "done": False, "left": data["qty"]})
        else:
            items.update(item["id"], done=True)
            done.append({"id": item["id"], "text": item["text"], "done": True, "left": None})
    return done


def note(done: List[Dict[str, Any]]) -> str:
    """The line the model gets about what was already done."""
    parts = [f"«{d['text']}» خلص" if d["done"] else f"«{d['text']}» ضل منه {d['left']:g}" for d in done]
    return ("نفّذت هلأ على قائمة التسوق: " + "، ".join(parts)
            + ". احكيله إنك شطبتيهم. لو ذكر سعر، سجّلي المصروف بـ remember.")
