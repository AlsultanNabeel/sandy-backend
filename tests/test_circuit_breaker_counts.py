"""The breaker opens when the provider is down, not when one request was wrong.

A refused prompt (content filter, context too long) is the service answering: it used to
count as an outage, and five in a row cut every customer off the model for a minute."""
import pytest

from app.utils.circuit_breaker import CircuitBreaker


class _Answered(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class _Response:
    def __init__(self, status):
        self.status_code = status


class _HTTPError(Exception):
    """requests' shape: the status sits on the response."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = _Response(status)


def _fail_times(cb, exc, n):
    def _raise():
        raise exc
    for _ in range(n):
        with pytest.raises(type(exc)):
            cb.call(_raise)


@pytest.mark.parametrize("exc", [_Answered(400), _Answered(404), _HTTPError(400)])
def test_requests_the_service_refused_do_not_open_it(exc):
    cb = CircuitBreaker("t", failure_threshold=3)
    _fail_times(cb, exc, 6)
    assert cb.state == "CLOSED"


@pytest.mark.parametrize("exc", [_Answered(503), _Answered(429), _HTTPError(502),
                                 ConnectionError("reset"), TimeoutError("slow")])
def test_an_outage_still_opens_it(exc):
    cb = CircuitBreaker("t", failure_threshold=3)
    _fail_times(cb, exc, 3)
    assert cb.state == "OPEN"
