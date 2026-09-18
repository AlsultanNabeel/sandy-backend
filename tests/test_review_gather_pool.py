"""gather() called from inside the shared pool must not starve it."""
from concurrent.futures import wait

from app.utils.thread_pool import gather, sandy_executor


def test_gather_from_every_worker_at_once_finishes():
    def _job():
        return gather({"a": lambda: 1, "b": lambda: 2})

    futs = [sandy_executor.submit(_job) for _ in range(20)]
    done, not_done = wait(futs, timeout=10)
    assert not not_done, "pool deadlocked: workers waiting on their own queue"
    assert all(f.result() == {"a": 1, "b": 2} for f in done)


def test_a_failing_job_is_none_not_fatal():
    out = gather({"ok": lambda: 1, "bad": lambda: 1 / 0})
    assert out == {"ok": 1, "bad": None}
