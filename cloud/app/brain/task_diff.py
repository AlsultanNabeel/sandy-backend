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

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app.brain import lang

# Moves by itself between two reads of the same data: no news.
MOVES_BY_ITSELF = frozenset({"last_seen", "to", "now", "read_at", "checked_at", "ago"})
# The fields a row's identity is read from, in order.
_KEYS = ("id", "url", "device", "name", "title")
# The top-level words compared as text.
_TEXTS = ("reply", "text", "summary", "answer", "body")
# A list's change the template tells: rows of a list, added, removed, ticked, renamed or moved.
_TOLD_FIELDS = {"done", "done_at", "text", "list"}


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


# What a «new only» task remembers having seen: each row's key, hashed, with when it was first
# seen; the newest `SEEN_MAX`, none older than `SEEN_DAYS`, so the state never grows without end.
SEEN_MAX, SEEN_DAYS = 500, 30


def _seen_key(row: Dict[str, Any]) -> str:
    return hashlib.sha256(_key(row).encode()).hexdigest()[:16]


def remember(found: Any, kept: Optional[Dict[str, str]], now: datetime) -> Dict[str, str]:
    """What it has seen, with what ``found`` has now."""
    floor = (now - timedelta(days=SEEN_DAYS)).isoformat()
    out = {k: at for k, at in (kept or {}).items() if isinstance(at, str) and at >= floor}
    for rows in _rows(found).values():
        for r in rows:
            out.setdefault(_seen_key(r), now.isoformat())
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True)[:SEEN_MAX])


def only_new(diff: Dict[str, Any], kept: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """The change of a «new only» task: rows never seen before, and nothing that went away or
    changed (a story dropping off a feed is no news, nor one coming back)."""
    known = kept or {}
    return {**diff, "added": [r for r in diff["added"] if _seen_key(r) not in known], "removed": [],
            "changed": [], "numbers": [], "paragraphs_removed": []}


def from_events(log: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The difference the log says, in the order it happened: rows by their id, each with its
    words and its list (`events.label`), so the template and the guard read it as any other."""
    out: Dict[str, Any] = {"added": [], "removed": [], "changed": [], "numbers": [],
                           "paragraphs_added": [], "paragraphs_removed": []}
    for e in log:
        if e["op"] == "hidden":
            continue                      # a done item cleared from view is no news
        base = {"id": e["row"], "text": e.get("label"),
                **{k: e[k] for k in ("list", "kind") if e.get(k)}}
        if e["op"] == "added":
            out["added"].append({**base, **(e.get("after") or {})})
        elif e["op"] == "removed":
            out["removed"].append({**base, **(e.get("before") or {})})
        else:
            before, after = e.get("before") or {}, e.get("after") or {}
            out["changed"].append({"before": {**base, "text": before.get("text", base["text"]), **before},
                                   "after": {**base, **after}, "fields": sorted(after)})
    return out


def empty(diff: Dict[str, Any]) -> bool:
    return not any(diff.values())


def _name(row: Dict[str, Any]) -> str:
    return str(row.get("text") or row.get("title") or row.get("name") or row.get("device") or "").strip()


def list_name(raw: str) -> str:
    """A list as he sees it, in his language: «قائمة التسوق», «Shopping list»; a project list
    by its own name; a list the kinds do not know as it is."""
    from app.blocks import kinds
    name = str(raw or "")
    kind = kinds.get_kind(kinds.LIST, name)
    if kind is None:
        return name
    if kind.name.endswith(":"):
        return name.partition(":")[2] or name
    return lang.say("list_name", label=kind.ar if lang.current() == lang.AR else kind.en)


def template(diff: Dict[str, Any]) -> Optional[str]:
    """A simple list's change in his language, with no model: rows of a list added, removed,
    ticked or renamed. None for anything else (the model explains it)."""
    if diff["numbers"] or diff["paragraphs_added"] or diff["paragraphs_removed"]:
        return None
    rows = [*diff["added"], *diff["removed"], *(c["after"] for c in diff["changed"])]
    if not rows or not all(r.get("list") and r.get("text") for r in rows):
        return None
    if any(not set(c["fields"]) <= _TOLD_FIELDS for c in diff["changed"]):
        return None
    lines = _grouped("list_added", diff["added"], by_list=True)
    lines += _grouped("list_removed", diff["removed"], by_list=True)
    for c in diff["changed"]:
        if "text" in c["fields"]:
            lines.append(lang.say("list_renamed", before=c["before"]["text"], after=c["after"]["text"]))
        if "list" in c["fields"]:
            lines.append(lang.say("list_moved", text=c["after"]["text"], list=list_name(c["after"]["list"])))
    ticked = [c["after"] for c in diff["changed"] if "done" in c["fields"]]
    lines += _grouped("list_done", [r for r in ticked if r.get("done")])
    lines += _grouped("list_reopened", [r for r in ticked if not r.get("done")])
    return "\n".join(lines)


# A watched page's items told at most, then «and N more» (the email links the task).
MAX_TOLD = 15
PAGE_OPS = ("added", "removed", "changed")


def page_items(diff: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
    """A listing's change as its items, ``{op, title, url}``, for the code to tell and the email
    to link; None when the change is not only a page's items."""
    if diff["numbers"] or diff["paragraphs_added"] or diff["paragraphs_removed"]:
        return None
    rows = [*(("added", r) for r in diff["added"]), *(("removed", r) for r in diff["removed"]),
            *(("changed", c["after"]) for c in diff["changed"])]
    if not rows or not all(r.get("url") and r.get("title") and not r.get("list") for _, r in rows):
        return None
    return [{"op": op, "title": str(r["title"]), "url": str(r["url"])} for op, r in rows]


def page_body(items: List[Dict[str, str]], site: str) -> str:
    """The items in plain words, in his language: each kind of change, its titles, «and N more»."""
    shown, lines = items[:MAX_TOLD], []
    for op in PAGE_OPS:
        group = [i for i in shown if i["op"] == op]
        if group:
            lines.append(lang.say(f"page_{op}", site=site))
            lines += [f"«{i['title']}»" for i in group]
    if len(items) > MAX_TOLD:
        lines.append(lang.say("mail_more", n=lang.number(len(items) - MAX_TOLD)))
    return "\n".join(lines)


def _grouped(key: str, rows: List[Dict[str, Any]], *, by_list: bool = False) -> List[str]:
    """One line per row, or one line for several rows with the same change (and list)."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(str(r.get("list")) if by_list else "", []).append(r)
    lines = []
    for raw, same in groups.items():
        where = {"list": list_name(raw)} if by_list else {}
        if len(same) == 1:
            lines.append(lang.say(key, text=same[0]["text"], **where))
        else:
            lines.append(lang.say(f"{key}_many", n=lang.number(len(same)),
                                  names=_listed([f"«{r['text']}»" for r in same]), **where))
    return lines


def _listed(names: List[str]) -> str:
    """The first names, then «and more»."""
    listed = lang.say("sep").join(names[:_SHOWN])
    return lang.say("state_more", names=listed) if len(names) > _SHOWN else listed


# How many names the state now shows before «and more».
_SHOWN = 5


def describe(found: Any) -> str:
    """How things are now, in a line of his language: what a task saw when it started."""
    rows = [r for v in _rows(found).values() for r in v]
    if rows:
        ticked = all("done" in r for r in rows)
        open_rows = [r for r in rows if not r.get("done")] if ticked else rows
        listed = _listed([f"«{_name(r)}»" for r in open_rows if _name(r)])
        done = lang.number(len(rows) - len(open_rows))
        if ticked and not open_rows:
            return lang.say("state_all_done", done=done)
        if ticked:
            return lang.say("state_list", open=lang.number(len(open_rows)), done=done, names=listed)
        return lang.say("state_rows", n=lang.number(len(rows)), names=listed)
    numbers = _numbers(found)
    if numbers:
        return lang.say("state_numbers", pairs=lang.say("sep").join(
            f"{k} {v:g}" for k, v in list(numbers.items())[:_SHOWN]))
    text = _paragraphs(_texts(found))
    return text[0][:160] if text else lang.say("state_nothing")


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

