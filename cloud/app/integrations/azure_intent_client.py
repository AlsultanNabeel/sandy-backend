"""Azure OpenAI client for intent routing (native function calling) and JSON mode."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.config import AZURE_OPENAI_API_VERSION
from app.utils.circuit_breaker import CircuitBreaker
import logging

logger = logging.getLogger(__name__)

DEFAULT_AZURE_INTENT_DEPLOYMENT = (
    os.getenv("AZURE_OPENAI_ROUTER_DEPLOYMENT", "").strip()
    or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "sandy-chat")
)

# Upper bound for a hung call, not a latency target.
AZURE_INTENT_TIMEOUT_S = float(os.getenv("AZURE_INTENT_TIMEOUT_S", "12"))

_CACHED_AZURE_CLIENT: Any = None
_CACHED_CLIENT_KEY: tuple = ()


def _get_azure_client(api_key: str, api_version: str, endpoint: str) -> Any:
    global _CACHED_AZURE_CLIENT, _CACHED_CLIENT_KEY
    key = (api_key, api_version, endpoint)
    if _CACHED_AZURE_CLIENT is not None and _CACHED_CLIENT_KEY == key:
        return _CACHED_AZURE_CLIENT

    from openai import AzureOpenAI

    _CACHED_AZURE_CLIENT = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
        # SDK retries would triple the timeout; we have our own fallback chain.
        max_retries=0,
    )
    _CACHED_CLIENT_KEY = key
    return _CACHED_AZURE_CLIENT


# Scanned by name so 'error' in the error repr is never mistaken for a param.
_TUNABLE_PARAMS = (
    "max_tokens", "max_completion_tokens", "temperature", "top_p",
    "frequency_penalty", "presence_penalty", "logprobs", "tool_choice",
    "reasoning_effort",
)


def _rejected_param(exc: Exception) -> Optional[str]:
    param = getattr(exc, "param", None)
    if param:
        return str(param)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        param = (err.get("param") if isinstance(err, dict) else None) or body.get("param")
        if param:
            return str(param)
    msg = str(exc)
    for name in _TUNABLE_PARAMS:
        if f"'{name}'" in msg:
            return name
    return None


# Errors only, no breaker `timeout=`: its shared pool would count queue time as
# failure under load. The SDK's per-request timeout is the deadline.
_cb = CircuitBreaker(
    name="azure_intent",
    failure_threshold=5,
    recovery_timeout=30.0,
)


def _create_chat_resilient(client: Any, kwargs: Dict[str, Any]) -> Any:
    """create() through the breaker, remapping/dropping params a model rejects (400).

    The remap loop is one breaker call, so param quirks don't trip the breaker.
    """
    return _cb.call(_create_chat_adapting, client, kwargs)


# Params each model refused, learned once per process to avoid a 400 round trip per call.
_ADAPTED: Dict[str, Dict[str, Optional[str]]] = {}


def _apply_known_quirks(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    for param, renamed in _ADAPTED.get(str(kwargs.get("model", "")), {}).items():
        if param in kwargs:
            value = kwargs.pop(param)
            if renamed:
                kwargs[renamed] = value
    return kwargs


def _create_chat_adapting(client: Any, kwargs: Dict[str, Any]) -> Any:
    kwargs = _apply_known_quirks(dict(kwargs))
    quirks = _ADAPTED.setdefault(str(kwargs.get("model", "")), {})
    _protected = {"model", "messages", "tools"}
    for _ in range(4):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            param = _rejected_param(exc)
            if param == "max_tokens" and "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                quirks["max_tokens"] = "max_completion_tokens"
                continue
            if param and param in kwargs and param not in _protected:
                kwargs.pop(param)
                quirks[param] = None
                logger.info("[azure] %s rejects %s — dropped from now on",
                            kwargs.get("model"), param)
                continue
            raise
    return client.chat.completions.create(**kwargs)


def _log_azure_usage(response: Any) -> None:
    """Log token usage, cache hits and estimated cost. Must never fail the turn."""
    try:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        in_tok = getattr(usage, "prompt_tokens", 0)
        out_tok = getattr(usage, "completion_tokens", 0)
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        non_cached_in = max(in_tok - cached, 0)
        rate_in = float(os.getenv("AZURE_COST_IN_PER_1M", "0.15"))
        rate_cached = float(os.getenv("AZURE_COST_CACHED_PER_1M", "0.075"))
        rate_out = float(os.getenv("AZURE_COST_OUT_PER_1M", "0.60"))
        cost = (
            non_cached_in * rate_in + cached * rate_cached + out_tok * rate_out
        ) / 1_000_000
        # %s not %d: a non-numeric field would fail inside the log handler, past this except.
        if cached:
            pct = (cached / in_tok * 100) if in_tok else 0
            logger.info(
                "[Azure] in=%s (cached=%s %.0f%%) out=%s ~$%.5f",
                in_tok, cached, pct, out_tok, cost,
            )
        else:
            logger.info("[Azure] in=%s out=%s ~$%.5f", in_tok, out_tok, cost)
    except (TypeError, ValueError, AttributeError) as exc:
        logger.warning("[Azure] usage log skipped: %s", exc)


class AzureIntentClient:
    """Azure OpenAI client for routing and small JSON/text generations."""

    def __init__(self):
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        self.api_version = AZURE_OPENAI_API_VERSION
        self.model_name = DEFAULT_AZURE_INTENT_DEPLOYMENT.strip()

    def _generate_with_gemini(
        self,
        prompt: str,
        *,
        response_mime_type: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """One-shot completion (name kept from the old Gemini client); JSON mode unless text/plain."""
        if not (self.api_key and self.endpoint):
            raise RuntimeError(
                "Azure OpenAI not configured: AZURE_OPENAI_API_KEY/ENDPOINT missing"
            )

        client = _get_azure_client(self.api_key, self.api_version, self.endpoint)
        messages = [{"role": "user", "content": prompt}]

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0,
            "max_tokens": max_output_tokens or 600,
            "timeout": AZURE_INTENT_TIMEOUT_S,
        }
        if (response_mime_type or "application/json") == "application/json":
            kwargs["response_format"] = {"type": "json_object"}
        response = _create_chat_resilient(client, kwargs)

        _log_azure_usage(response)

        choice = response.choices[0] if response.choices else None
        if not choice:
            return ""
        content = getattr(choice.message, "content", None)
        return str(content).strip() if content else ""

    def complete_with_tools(
        self,
        system: str,
        user: str,
        tools: list,
        *,
        tool_choice: str = "auto",
        temperature: float = 0.0,
        max_tokens: int = 700,
    ) -> Any:
        """Native function calling; returns the raw message (``.content``/``.tool_calls``) or None.

        ``system`` and ``tools`` are the stable, cached prefix; only ``user`` varies.
        """
        if not (self.api_key and self.endpoint):
            raise RuntimeError(
                "Azure OpenAI not configured: AZURE_OPENAI_API_KEY/ENDPOINT missing"
            )
        client = _get_azure_client(self.api_key, self.api_version, self.endpoint)
        response = _create_chat_resilient(client, {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Reasoning models otherwise think for seconds; others reject it and it gets dropped.
            "reasoning_effort": "minimal",
            "timeout": AZURE_INTENT_TIMEOUT_S,
        })
        _log_azure_usage(response)
        choice = response.choices[0] if response.choices else None
        return choice.message if choice else None
