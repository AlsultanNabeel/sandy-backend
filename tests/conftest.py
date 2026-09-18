import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))


@pytest.fixture(autouse=True)
def _reset_tool_registry():
    """يمسح الـ ToolRegistry singletons بين كل test."""
    from app.agent.tools.registry import _reset_for_testing as _reset_reg
    from app.agent.tools.setup import _reset_for_testing as _reset_setup
    _reset_reg()
    _reset_setup()
    yield
    _reset_reg()
    _reset_setup()


@pytest.fixture(autouse=True)
def _fresh_circuit_breakers(monkeypatch):
    """Every test starts with the model breakers closed.

    They are module-level singletons, so five failures in one test (a stubbed
    client that raises, a missing key) left the breaker OPEN for every test
    after it — and a later test that drove a real code path through it failed
    or passed depending on the order the suite happened to run in.
    """
    from app.integrations import azure_intent_client, openai_client
    from app.utils.circuit_breaker import CircuitBreaker

    for mod in (azure_intent_client, openai_client):
        old = mod._cb
        monkeypatch.setattr(mod, "_cb", CircuitBreaker(
            name=old.name, failure_threshold=old.failure_threshold,
            recovery_timeout=old.recovery_timeout))
    yield
