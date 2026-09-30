import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))


@pytest.fixture(autouse=True)
def _fresh_circuit_breakers(monkeypatch):
    """Every test starts with the model breaker closed.

    It is a module-level singleton, so five failures in one test (a stubbed
    client that raises, a missing key) left the breaker OPEN for every test
    after it — and a later test that drove a real code path through it failed
    or passed depending on the order the suite happened to run in.
    """
    from app.integrations import openai_client
    from app.utils.circuit_breaker import CircuitBreaker

    old = openai_client._cb
    monkeypatch.setattr(openai_client, "_cb", CircuitBreaker(
        name=old.name, failure_threshold=old.failure_threshold,
        recovery_timeout=old.recovery_timeout))
    yield
