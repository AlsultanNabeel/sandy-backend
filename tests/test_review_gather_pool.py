"""gather() called from inside the shared pool must not starve it."""
from concurrent.futures import ThreadPoolExecutor, wait

from app.utils import thread_pool
from app.utils.thread_pool import gather


def test_gather_from_every_worker_at_once_finishes(monkeypatch):
    # A private pool shaped like the real one (another test shuts the shared
    # one down at exit of its own scope).
    pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix=thread_pool._WORKER_PREFIX)
    monkeypatch.setattr(thread_pool, "sandy_executor", pool)
    try:
        def _job():
            return gather({"a": lambda: 1, "b": lambda: 2})

        futs = [pool.submit(_job) for _ in range(20)]
        done, not_done = wait(futs, timeout=10)
        assert not not_done, "pool deadlocked: workers waiting on their own queue"
        assert all(f.result() == {"a": 1, "b": 2} for f in done)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def test_a_failing_job_is_none_not_fatal(monkeypatch):
    pool = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(thread_pool, "sandy_executor", pool)
    try:
        assert gather({"ok": lambda: 1, "bad": lambda: 1 / 0}) == {"ok": 1, "bad": None}
    finally:
        pool.shutdown(wait=False)
