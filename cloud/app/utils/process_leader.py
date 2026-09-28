"""Pick one process per machine to run a periodic job (gunicorn runs 2 workers).

A kernel flock is released however the holder dies, so a replacement worker
takes over with no TTL. Scope is one host; guarded jobs are idempotent across hosts.
"""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# Held open for the process lifetime: closing (or GC) would release the lock.
_held: dict[str, object] = {}


def claim_leadership(job: str) -> bool:
    """True if this process should run ``job``.

    Fails open (True) when locking is unavailable: running twice is safe, zero times is not.
    """
    if job in _held:
        return True
    try:
        import fcntl
    except ImportError:
        logger.info("[leader] no fcntl on this platform — %s runs unguarded", job)
        return True

    path = os.path.join(tempfile.gettempdir(), f"sandy-leader-{job}.lock")
    try:
        handle = open(path, "w")  # noqa: SIM115 — held for the process lifetime
    except OSError as exc:
        logger.warning("[leader] cannot open %s (%s) — %s runs unguarded", path, exc, job)
        return True

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        logger.info("[leader] %s is owned by another worker; not starting it here", job)
        return False

    handle.write(f"{os.getpid()}\n")
    handle.flush()
    _held[job] = handle
    logger.info("[leader] pid %s owns %s on this machine", os.getpid(), job)
    return True
