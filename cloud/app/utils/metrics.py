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
    # HTTP / webhook metrics
    telegram_webhook_ingress_total = Counter(
        "sandy_telegram_webhook_ingress_total", "Total telegram webhook ingresses"
    )
    telegram_webhook_dedup_total = Counter(
        "sandy_telegram_webhook_dedup_total", "Total telegram webhook dedup hits"
    )
    telegram_webhook_processing_seconds = Histogram(
        "sandy_telegram_webhook_processing_seconds", "Webhook processing latency"
    )

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

    # Project Builder metrics
    agent_resume_state_saved_total = Counter(
        "sandy_agent_resume_state_saved_total", "Times agent resume_state was saved"
    )
    agent_resume_signal_total = Counter(
        "sandy_agent_resume_signal_total", "Times owner signalled resume"
    )
    agent_resume_wait_seconds = Histogram(
        "sandy_agent_resume_wait_seconds", "Time spent waiting for resume"
    )
    agent_resume_wait_resumed_total = Counter(
        "sandy_agent_resume_wait_resumed_total", "Resume waits that completed successfully"
    )
    agent_resume_wait_shutdown_total = Counter(
        "sandy_agent_resume_wait_shutdown_total", "Resume waits interrupted by shutdown"
    )
    agent_resume_wait_timeout_total = Counter(
        "sandy_agent_resume_wait_timeout_total", "Resume waits that expired naturally"
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
    inc_webhook_ingress = _noop
    inc_webhook_dedup = _noop
    observe_webhook_duration = _noop
    observe_llm_completion = _noop
    inc_llm_completion_success = _noop
    inc_llm_completion_failure = _noop
    inc_agent_resume_saved = _noop
    inc_agent_resume_signal = _noop
    observe_resume_wait = _noop
    inc_resume_wait_resumed = _noop
    inc_resume_wait_shutdown = _noop
    inc_resume_wait_timeout = _noop
    inc_error_log_success = _noop
    inc_error_log_failure = _noop

    def metrics_wsgi() -> (bytes, str):
        return b"", "text/plain"
