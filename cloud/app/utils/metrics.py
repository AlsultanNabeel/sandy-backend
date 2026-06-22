"""Simple Prometheus metrics wrapper with safe no-op fallback.

The module keeps the application code free from Prometheus-specific details
and makes metrics calls safe when the dependency is absent during tests.
"""

_ENABLED = True
try:
    from prometheus_client import Counter, Histogram, generate_latest
    from prometheus_client import CONTENT_TYPE_LATEST
except Exception:
    _ENABLED = False


def _noop(*_args, **_kwargs):
    return None


if _ENABLED:
    # LLM metrics
    llm_completion_seconds = Histogram(
        "sandy_llm_completion_seconds", "LLM chat completion latency"
    )
    llm_completion_success_total = Counter(
        "sandy_llm_completion_success_total", "Successful LLM completions"
    )
    llm_completion_failure_total = Counter(
        "sandy_llm_completion_failure_total", "Failed LLM completions"
    )

    # Error persistence metrics
    error_log_total = Counter(
        "sandy_error_log_total", "Unhandled errors persisted successfully"
    )
    error_log_failure_total = Counter(
        "sandy_error_log_failure_total", "Unhandled errors that failed to persist"
    )

    def metrics_wsgi() -> (bytes, str):
        return generate_latest(), CONTENT_TYPE_LATEST

else:
    # No-op shim
    observe_llm_completion = _noop
    inc_llm_completion_success = _noop
    inc_llm_completion_failure = _noop
    inc_error_log_success = _noop
    inc_error_log_failure = _noop

    def metrics_wsgi() -> (bytes, str):
        return b"", "text/plain"
