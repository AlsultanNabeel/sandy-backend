"""Find one row by what the user called it ("delete the gym task").

The ladder is `features/tasks_matcher.resolve_task_reference_for_write`'s —
exact, then contained, then fuzzy >= 0.72 — on its own normaliser, applied to
any block row that has ``text``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.features.tasks_matcher import _task_match_key, _task_match_score

FUZZY = 0.72


def match_rows(reference: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``{"status": matched|ambiguous|not_found|missing, "row", "matches"}``."""
    ref = _task_match_key(reference)
    if not ref:
        return {"status": "missing", "row": None, "matches": []}
    ladder = (
        lambda r: _task_match_key(r.get("text", "")) == ref,
        lambda r: ref in _task_match_key(r.get("text", "")),
        lambda r: _task_match_score(ref, r.get("text", "")) >= FUZZY,
    )
    for test in ladder:
        hits = [r for r in rows if test(r)]
        if len(hits) == 1:
            return {"status": "matched", "row": hits[0], "matches": hits}
        if hits:
            return {"status": "ambiguous", "row": None, "matches": hits}
    return {"status": "not_found", "row": None, "matches": []}
