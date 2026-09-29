"""OpenAI / Azure OpenAI chat completion (Azure first) behind a circuit breaker."""

import os
from typing import Any, Callable, Dict, List, Optional

from app.utils.circuit_breaker import CircuitBreaker, CircuitOpenError

_cb = CircuitBreaker(name="openai", failure_threshold=5, recovery_timeout=60.0)

# Hang ceiling when the caller passes no timeout.
DEFAULT_CHAT_TIMEOUT_S = float(os.getenv("OPENAI_CHAT_TIMEOUT_S", "15"))


def _chat_client_and_model(
    openai_client: Any,
    azure_openai_client: Optional[Any] = None,
    openai_model: Optional[str] = None,
    azure_chat_deployment: Optional[str] = None,
    prefer_azure: bool = True,
    model_hint: Optional[str] = None,
) -> tuple:
    if prefer_azure and azure_openai_client is not None:
        model_name = model_hint or azure_chat_deployment or openai_model
        return azure_openai_client, model_name

    model_name = model_hint or openai_model
    return openai_client, model_name


def create_chat_completion(
    messages: List[Dict[str, Any]],
    openai_client: Any,
    azure_openai_client: Optional[Any] = None,
    openai_model: Optional[str] = None,
    azure_chat_deployment: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 500,
    response_format: Optional[Dict[str, Any]] = None,
    prefer_azure: bool = True,
    model_hint: Optional[str] = None,
    timeout: Optional[float] = None,
    stream: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """Unified chat completion with Azure-first routing and circuit breaker."""
    client, model_name = _chat_client_and_model(
        openai_client=openai_client,
        azure_openai_client=azure_openai_client,
        openai_model=openai_model,
        azure_chat_deployment=azure_chat_deployment,
        prefer_azure=prefer_azure,
        model_hint=model_hint,
    )

    kwargs: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    kwargs["timeout"] = timeout if timeout is not None else DEFAULT_CHAT_TIMEOUT_S
    if stream:
        kwargs["stream"] = True
    if tools:
        kwargs["tools"] = tools

    # Same per-model param adaptation as the router.
    from app.integrations.azure_intent_client import _create_chat_adapting

    try:
        return _cb.call(_create_chat_adapting, client, kwargs)
    except CircuitOpenError:
        raise RuntimeError("[OpenAI] Circuit OPEN — AI service temporarily unavailable")


def make_chat_completion_fn(
    openai_client: Any,
    azure_openai_client: Optional[Any] = None,
    openai_model: Optional[str] = None,
    azure_chat_deployment: Optional[str] = None,
) -> Callable[..., Any]:

    def _bound(
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        response_format: Optional[Dict[str, Any]] = None,
        prefer_azure: bool = True,
        model_hint: Optional[str] = None,
        timeout: Optional[float] = None,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        return create_chat_completion(
            messages=messages,
            openai_client=openai_client,
            azure_openai_client=azure_openai_client,
            openai_model=openai_model,
            azure_chat_deployment=azure_chat_deployment,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            prefer_azure=prefer_azure,
            model_hint=model_hint,
            timeout=timeout,
            stream=stream,
            tools=tools,
        )

    return _bound
