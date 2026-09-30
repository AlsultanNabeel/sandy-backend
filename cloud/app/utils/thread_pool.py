"""Shared background thread pool; jobs carry the caller's context (tenant)."""

import contextvars
import logging
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
