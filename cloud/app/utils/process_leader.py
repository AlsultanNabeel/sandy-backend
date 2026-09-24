"""Pick exactly one process on this machine to run a periodic job.

`Procfile` runs gunicorn with two workers, and every worker runs `bootstrap()`,
so every periodic job starts twice on one dyno. Correctness was never the
problem — the nudge send claims an atomic per-day lock and each scene revert is
claimed with a find-and-delete, and both modules say so — but the *scans* are
not claimed: `users_with_due_timers` sweeps the collection once a minute in each
worker, for ever, and half of that work exists only because a process was
forked.

**A file lock, not a database lease.** The workers sharing the problem also
share a filesystem — they are processes on one dyno — so this needs no
coordination protocol, no TTL, and no clock. `flock(LOCK_EX | LOCK_NB)` on a
path under the temp directory is decided by the kernel, and the lock is released
by the kernel when the holder exits *however* it exits: crash, OOM kill,
`SIGKILL` from a platform recycling the dyno. A database lease has to guess that
with a timeout, and the guess is the part that goes wrong — too short and two
workers run, too long and nothing runs after a crash.

So failover is free: gunicorn replaces a dead worker, the replacement runs
`bootstrap()`, and its claim succeeds because the dead worker's lock is already
gone. Nothing polls and nothing expires.

**The scope is one machine.** Two dynos would each elect a leader, and that is
the right reading of this file's name — it picks one process per host, not one
in the world. Everything it currently guards is idempotent across hosts anyway
(that is what the per-day and per-timer claims are for); anything that is not
needs a real distributed lock, not this.
"""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# The open file descriptors, kept for the life of the process. Closing one (or
# letting it be garbage collected) releases its lock, which would silently let a
# second worker in — so they are held here on purpose and never closed.
_held: dict[str, object] = {}


def claim_leadership(job: str) -> bool:
    """True if this process should run ``job`` — exactly one on this machine.

    Returns True unconditionally on a platform without ``fcntl`` (Windows), and
    if the lock file cannot be opened at all. Both are the safe direction: the
    jobs this guards are each individually claimed before they act, so running
    twice costs duplicated reads, while running zero times means the reminders
    never go out.
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
        # Another worker on this dyno holds it. Expected on every worker but one.
        handle.close()
        logger.info("[leader] %s is owned by another worker; not starting it here", job)
        return False

    handle.write(f"{os.getpid()}\n")
    handle.flush()
    _held[job] = handle
    logger.info("[leader] pid %s owns %s on this machine", os.getpid(), job)
    return True
