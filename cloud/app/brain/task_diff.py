"""What changed between two reads of a task's check, computed by the code (owner, 30 Oct 2026).

The model was once handed the two reads and asked what was new; on a list longer than the
rows it was shown it named what had only entered the window («انضاف ليمون» when «رمان» was
added). Now the difference is computed here, the same for any source, and the model is only
ever handed it to explain:

  rows      a list of records (a list's items, search results, devices), each known by its
            id, else its link, its device, its name or its title: what was added, removed,
            and which fields of the rest changed (a search result's snippet moves on its own
            and is not one)
  text      paragraphs added and removed
  numbers   each number before and after, by its path («spending.total»)

What moves by itself between two reads (a device's last seen, a period's end) is no change.
A simple list's change is told by a template with no model (`template`), and a message that
names a row that did not change is never sent (`faithful`).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from app.brain import lang

# Moves by itself between two reads of the same data: no news.
MOVES_BY_ITSELF = frozenset({"last_seen", "to", "now", "read_at", "checked_at", "ago"})
# The fields a row's identity is read from, in order.
_KEYS = ("id", "url", "device", "name", "title")
# The top-level words compared as text.
_TEXTS = ("reply", "text", "summary", "answer", "body")
# A list's change the template tells: rows of a list, added, removed, ticked or renamed.
_TOLD_FIELDS = {"done", "text"}


def _key(row: Dict[str, Any]) -> str:
    for k in _KEYS:
        if row.get(k) not in (None, ""):
            return f"{k}:{row[k]}"
    return json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)


def _rows(data: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Every list of records in ``data``, by the key it is under."""
    if not isinstance(data, dict):
        return {}
    return {k: [r for r in v if isinstance(r, dict)] for k, v in data.items()
            if isinstance(v, list) and any(isinstance(r, dict) for r in v)}


def _fields(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    skip = MOVES_BY_ITSELF | ({"text"} if after.get("url") else set())
    return sorted(k for k in set(before) | set(after)
                  if k not in skip and before.get(k) != after.get(k))


def _numbers(data: Any, path: str = "") -> Dict[str, float]:
    out: Dict[str, float] = {}
    if isinstance(data, dict):
        has_rows = bool(_rows(data))
        for k, v in data.items():
            # How many rows there are is the rows' own news, told by them.
            if k in MOVES_BY_ITSELF or (has_rows and k == "count"):
                continue
            out.update(_numbers(v, f"{path}.{k}" if path else k))
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        out[path] = data
    return out


def _paragraphs(text: Any) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()]


def _texts(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return "\n\n".join(str(data[k]) for k in _TEXTS if isinstance(data.get(k), str))
    return ""


def compute(before: Any, now: Any) -> Dict[str, Any]:
    """What changed from ``before`` to ``now``."""
    out: Dict[str, Any] = {"added": [], "removed": [], "changed": [], "numbers": [],
                           "paragraphs_added": [], "paragraphs_removed": []}
    old_rows, new_rows = _rows(before), _rows(now)
    for name in sorted(set(old_rows) | set(new_rows)):
        old = {_key(r): r for r in old_rows.get(name, [])}
        new = {_key(r): r for r in new_rows.get(name, [])}
        out["added"] += [new[k] for k in new if k not in old]
        out["removed"] += [old[k] for k in old if k not in new]
        for k in new:
            if k in old:
                fields = _fields(old[k], new[k])
                if fields:
                    out["changed"].append({"before": old[k], "after": new[k], "fields": fields})
    old_n, new_n = _numbers(before), _numbers(now)
    out["numbers"] = [{"what": p, "before": old_n[p], "after": new_n[p]}
                      for p in sorted(set(old_n) & set(new_n)) if old_n[p] != new_n[p]]
    old_p, new_p = _paragraphs(_texts(before)), _paragraphs(_texts(now))
    out["paragraphs_added"] = [p for p in new_p if p not in old_p]
    out["paragraphs_removed"] = [p for p in old_p if p not in new_p]
    return out


def empty(diff: Dict[str, Any]) -> bool:
    return not any(diff.values())


def _name(row: Dict[str, Any]) -> str:
    return str(row.get("text") or row.get("title") or row.get("name") or row.get("device") or "").strip()


def template(diff: Dict[str, Any]) -> Optional[str]:
    """A simple list's change in his language, with no model: rows of a list added, removed,
    ticked or renamed. None for anything else (the model explains it)."""
    if diff["numbers"] or diff["paragraphs_added"] or diff["paragraphs_removed"]:
        return None
    rows = [*diff["added"], *diff["removed"], *(c["after"] for c in diff["changed"])]
    if not rows or not all("list" in r and r.get("text") for r in rows):
        return None
    if any(not set(c["fields"]) <= _TOLD_FIELDS for c in diff["changed"]):
        return None
    lines = [lang.say("list_added", text=r["text"], list=r["list"]) for r in diff["added"]]
    lines += [lang.say("list_removed", text=r["text"], list=r["list"]) for r in diff["removed"]]
    for c in diff["changed"]:
        if "text" in c["fields"]:
            lines.append(lang.say("list_renamed", before=c["before"]["text"], after=c["after"]["text"]))
        if "done" in c["fields"]:
            lines.append(lang.say("list_done" if c["after"].get("done") else "list_reopened",
                                  text=c["after"]["text"]))
    return "\n".join(lines)


def _plain(text: str) -> str:
    return re.sub(r"[ًٌٍَُِّْـ]", "", str(text or "")).lower()


def _names(rows: Iterable[Dict[str, Any]]) -> set:
    return {_plain(_name(r)) for r in rows if _name(r)}


def faithful(message: str, diff: Dict[str, Any], before: Any, now: Any) -> bool:
    """Whether ``message`` names only what changed: a row that is in either read and not in
    the difference may not be in it (a name inside a changed one, «رمان» in «رمان أحمر», is
    the changed one's)."""
    told = _names([*diff["added"], *diff["removed"],
                   *(r for c in diff["changed"] for r in (c["before"], c["after"]))])
    every = _names(r for rows in (*_rows(before).values(), *_rows(now).values()) for r in rows)
    text = _plain(message)
    for name in every - told:
        if name in text and not any(name in t for t in told):
            return False
    return True


def shown(diff: Dict[str, Any]) -> Dict[str, Any]:
    """The difference as the model is handed it: what changed and nothing else."""
    return {k: v for k, v in diff.items() if v}

