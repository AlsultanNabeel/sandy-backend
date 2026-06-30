import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

sandy_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="SandyWorker")


def submit_background(fn, *args, _label: str | None = None, **kwargs):
    """Run fire-and-forget work on the shared pool, logging any exception.

    Use this instead of raw threading.Thread for background work (see C3).
    Returns the Future (callers may ignore it).
    """
    label = _label or getattr(fn, "__name__", "task")

    def _runner():
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("[background] %s failed", label)

    return sandy_executor.submit(_runner)
