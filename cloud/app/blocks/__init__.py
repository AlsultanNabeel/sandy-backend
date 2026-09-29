"""The four building blocks of the rebuild: log, lists, schedules (+ summaries later).

Read and written by the brain (phase 2), /api/entries|items|schedules|kinds and
the schedule runner (phase 3); bootstrap creates the indexes.
"""

from __future__ import annotations

from app.blocks import entries, items, schedules


def init_blocks(mongo_db) -> None:
    """Create every block's indexes once, on the raw handle, like the other stores."""
    entries.init_entries_store(mongo_db)
    items.init_items_store(mongo_db)
    schedules.init_schedules_store(mongo_db)
