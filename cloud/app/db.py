"""The single process-wide Mongo handle (which database, never which tenant — see utils/tenant_db)."""

from __future__ import annotations

from typing import Any, Optional

_mongo_db: Optional[Any] = None


def configure(mongo_db: Any) -> None:
    """Register the Mongo handle (at boot, or in a test)."""
    global _mongo_db
    _mongo_db = mongo_db


def get_db() -> Optional[Any]:
    return _mongo_db


def reset() -> None:
    """Test hook: drop the handle."""
    global _mongo_db
    _mongo_db = None
