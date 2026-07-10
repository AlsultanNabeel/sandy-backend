"""Composition-root data-handle provider.

Feature stores used to each own a mutable ``_mongo_db`` module global, set by
their own ``init_*`` function — seventeen duplicated singletons, and seventeen
separate places a test had to reach into. They now share one seam: the
composition root (the agent boot in ``app.agent.facade.agent``, or a test) calls
:func:`configure` once, and every store reads the handle through :func:`get_db`.

This owns *which database*, never *which tenant*. Tenant isolation still runs on
top through :func:`app.utils.tenant_db.scoped`, which stamps ``current_user_id``
onto every query and insert. The two layers compose: ``scoped(get_db(), name)``
returns ``None`` when there is no database **or** no authenticated tenant, so the
existing ``if coll is None`` guard in every store keeps failing closed exactly as
before.
"""

from __future__ import annotations

from typing import Any, Optional

_mongo_db: Optional[Any] = None


def configure(mongo_db: Any) -> None:
    """Register the process-wide Mongo handle.

    Called once at boot, and by any test that needs a real/mock database.
    Idempotent — calling it again just swaps the handle.
    """
    global _mongo_db
    _mongo_db = mongo_db


def get_db() -> Optional[Any]:
    """The configured Mongo handle, or ``None`` before :func:`configure` runs."""
    return _mongo_db


def reset() -> None:
    """Drop the handle. Test hook so one test's database can't leak into the
    next — the per-store globals never reset between tests before this existed.
    """
    global _mongo_db
    _mongo_db = None
