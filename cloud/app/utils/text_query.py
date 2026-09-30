"""Case-insensitive text match fragments for Mongo queries.

User text is ``re.escape``d so it can't act as a pattern (``.*``, ReDoS).
"""

from __future__ import annotations

import re
from typing import Any, Dict


def contains(field: str, text: str) -> Dict[str, Any]:
    """Documents whose `field` contains `text`, ignoring case."""
    return {field: {"$regex": re.escape(str(text or "").strip()), "$options": "i"}}
