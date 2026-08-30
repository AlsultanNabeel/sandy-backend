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


def gather(jobs: "dict[str, object]") -> "dict[str, object]":
    """Run independent readers at the same time and return their results.

    **Serial round trips are the whole cost of building context.** The voice
    prompt was measured at six seconds before Gemini was even dialled, and
    almost all of it was thirty small queries to Atlas taken one at a time —
    each one fast, all of them waiting on the one before. Nothing in that set
    depends on anything else in it.

    ``jobs`` maps a name to a zero-argument callable. Every job runs with a copy
    of the caller's context, which is not optional here: the stores underneath
    are tenant-scoped and read the tenant from a context variable, so a job on a
    bare thread would quietly return an empty list instead of the user's data.

    A job that raises contributes ``None`` rather than taking the rest down.
    """
    if not jobs:
        return {}

    ctx = contextvars.copy_context()
    futures = {name: sandy_executor.submit(ctx.copy().run, fn)
               for name, fn in jobs.items()}
    out: "dict[str, object]" = {}
    for name, fut in futures.items():
        try:
            out[name] = fut.result()
        except Exception:  # noqa: BLE001 — one broken area, not the whole picture
            logger.debug("[gather] %s failed", name, exc_info=True)
            out[name] = None
    return out
