"""Circuit breaker: CLOSED → OPEN (failing) → HALF_OPEN (probing) → CLOSED."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Separate from the shared background pool so a hung provider can't starve it.
# Threads start lazily, so creating it at import costs nothing.
_timeout_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cb-timeout")


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:

    _CLOSED = "CLOSED"
    _OPEN = "OPEN"
    _HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        timeout: Optional[float] = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        # A call slower than this counts as a failure. None = no limit.
        self.timeout = timeout

        self._state = self._CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def _should_attempt(self) -> bool:
        with self._lock:
            if self._state == self._CLOSED:
                return True
            if self._state == self._OPEN:
                elapsed = time.monotonic() - (self._last_failure_time or 0)
                if elapsed >= self.recovery_timeout:
                    self._state = self._HALF_OPEN
                    logger.info(
                        f"[CB:{self.name}] → HALF_OPEN (probing after {elapsed:.0f}s)"
                    )
                    return True
                return False
            return True  # HALF_OPEN: allow a probe

    def _on_success(self) -> None:
        with self._lock:
            if self._state != self._CLOSED:
                logger.info(f"[CB:{self.name}] → CLOSED (recovered)")
            self._state = self._CLOSED
            self._failure_count = 0
            self._last_failure_time = None

    def _on_failure(self, exc: Exception) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if (
                self._state == self._HALF_OPEN
                or self._failure_count >= self.failure_threshold
            ):
                self._state = self._OPEN
                exc_summary = str(exc).splitlines()[0][:80] if str(exc) else type(exc).__name__
                logger.warning(
                    f"[CB:{self.name}] → OPEN after {self._failure_count} failures: {exc_summary}"
                )

    def _invoke(self, fn: Callable[..., Any], args: Any, kwargs: Any) -> Any:
        if self.timeout is None:
            return fn(*args, **kwargs)
        future = _timeout_pool.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=self.timeout)
        except FuturesTimeoutError as exc:
            # The thread keeps running, but the caller gets control back.
            future.cancel()
            raise TimeoutError(
                f"Circuit '{self.name}' call exceeded {self.timeout:.1f}s"
            ) from exc

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self._should_attempt():
            raise CircuitOpenError(
                f"Circuit '{self.name}' is OPEN — service unavailable"
            )
        try:
            result = self._invoke(fn, args, kwargs)
            self._on_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:
            self._on_failure(exc)
            raise
