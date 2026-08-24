import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

sandy_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="SandyWorker")


def submit_background(fn, *args, _label: str | None = None, **kwargs):
    """Run fire-and-forget work on the shared pool, logging any exception.

    Use this instead of raw threading.Thread for background work (see C3).
    Returns the Future (callers may ignore it).

    **The job carries the caller's context.**

    A pool worker starts with an empty set of context variables, and the active
    tenant is one of them — so a `scoped()` store touched by background work
    would find no tenant, read nothing, write nothing, and return a perfectly
    ordinary empty result. No exception, no log line, no symptom except that the
    thing quietly did not happen.

    That was survivable only because every background writer here happened to
    take its ids as explicit arguments and reach past `scoped()` to the raw
    collection — which is the hand-written-filter pattern that `tenant_db` was
    written to abolish. Propagating the context is what lets those callers move
    back onto `scoped()`, and it means new background work is correct by default
    instead of correct only if someone remembered.

    A fresh `copy_context()` per submit: a `Context` cannot be entered twice at
    the same time, so one shared copy would break under concurrency.
    """
    label = _label or getattr(fn, "__name__", "task")

    def _runner():
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("[background] %s failed", label)

    return sandy_executor.submit(contextvars.copy_context().run, _runner)
