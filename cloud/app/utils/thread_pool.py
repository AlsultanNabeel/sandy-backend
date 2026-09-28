"""Shared background thread pool; jobs carry the caller's context (tenant)."""

import contextvars
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_WORKER_PREFIX = "SandyWorker"
sandy_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix=_WORKER_PREFIX)


def submit_background(fn, *args, _label: str | None = None, **kwargs):
    """Run fire-and-forget work on the shared pool (C3), logging any exception.

    The job runs in a copy of the caller's context, so tenant-scoped stores still
    see the tenant (a bare worker would silently read and write nothing).
    """
    label = _label or getattr(fn, "__name__", "task")

    def _runner():
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("[background] %s failed", label)

    return sandy_executor.submit(contextvars.copy_context().run, _runner)


def gather(jobs: "dict[str, object]") -> "dict[str, object]":
    """Run name→callable jobs in parallel (with the caller's context); a failing job gives None.

    From inside a pool worker the jobs run inline, since waiting on our own pool can deadlock it.
    """
    if not jobs:
        return {}

    out: "dict[str, object]" = {}
    if threading.current_thread().name.startswith(_WORKER_PREFIX):
        for name, fn in jobs.items():
            try:
                out[name] = fn()
            except Exception:  # noqa: BLE001
                logger.warning("[gather] %s failed", name, exc_info=True)
                out[name] = None
        return out

    ctx = contextvars.copy_context()
    futures = {name: sandy_executor.submit(ctx.copy().run, fn)
               for name, fn in jobs.items()}
    for name, fut in futures.items():
        try:
            out[name] = fut.result()
        except Exception:  # noqa: BLE001
            logger.warning("[gather] %s failed", name, exc_info=True)
            out[name] = None
    return out
