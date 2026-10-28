"""Feature switches: every new feature ships behind one, off until turned on.

``SANDY_FLAGS`` is a JSON object, one key per switch: ``"all"`` turns it on for everyone,
a list of account ids for those accounts only.

    {"tasks": "all", "skills": ["3ab1c7f824c04e2aa3cd8bf0ca2f51d6"]}

A switch that is missing, or a value that cannot be read, is off; a setting that is not a
JSON object turns every switch off and is logged, never a crash. `on` is the one way the
code asks.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _switches() -> Dict[str, Any]:
    raw = os.getenv("SANDY_FLAGS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("[flags] SANDY_FLAGS is not JSON — every switch is off")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("[flags] SANDY_FLAGS is not a JSON object — every switch is off")
        return {}
    return parsed


def _allows(value: Any, user_id: str) -> bool:
    if value == "all":
        return True
    return isinstance(value, list) and bool(user_id) and user_id in {str(v) for v in value}


def on(name: str, user_id: str) -> bool:
    """Whether switch ``name`` is on for this account."""
    return _allows(_switches().get(name), str(user_id or ""))


def enabled_for(user_id: str) -> List[str]:
    """Every switch on for this account, sorted."""
    uid = str(user_id or "")
    return sorted(name for name, value in _switches().items() if _allows(value, uid))
