"""The four building blocks of the rebuild: log, lists, schedules (+ summaries later).

Phase 1: not wired into the agent, tools, API or bootstrap yet.
"""

from __future__ import annotations

from app.blocks import entries, items, schedules


def init_blocks(mongo_db) -> None:
    """Create every block's indexes once, on the raw handle, like the other stores."""
    entries.init_entries_store(mongo_db)
    items.init_items_store(mongo_db)
    schedules.init_schedules_store(mongo_db)
