"""The rebuilt agent (phase 2): one model call with native tools, in a loop, on the blocks.

Off unless ``SANDY_NEW_AGENT=1``. Chat (`api/server.py`) and voice
(`api/voice_ws/tools.py`) ask ``enabled()`` at call time and otherwise run the
old graph untouched. See ARCHITECTURE_MAP.md §2.13.
"""

from __future__ import annotations

from app import config


def enabled() -> bool:
    # Read at call time so a test (or a hot config reload) can flip it.
    return bool(config.SANDY_NEW_AGENT)
