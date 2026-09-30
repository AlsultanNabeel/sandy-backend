"""OpenAI / Azure OpenAI chat completion (Azure first) behind a circuit breaker.

`chat_fn()` is the process's one chat client (built on first use, C4);
`openai_direct_client()` is the fallback when Azure fails.
"""

import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from app.utils.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

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

    try:
        return _cb.call(_create_chat_adapting, client, kwargs)
    except CircuitOpenError:
        raise RuntimeError("[OpenAI] Circuit OPEN — AI service temporarily unavailable")


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
                logger.info("[openai] %s rejects %s — dropped from now on",
                            kwargs.get("model"), param)
                continue
            raise
    return client.chat.completions.create(**kwargs)


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


_chat_fn: Optional[Callable[..., Any]] = None
_direct_client: Any = None
_clients_lock = threading.Lock()


def chat_fn() -> Callable[..., Any]:
    """The shared chat-completion callable (Azure first, OpenAI direct second).

    Raises ConfigError with neither configured; the app refuses to boot without
    one (`config.validate_config`), so this only happens in a bare test.
    """
    global _chat_fn
    if _chat_fn is not None:
        return _chat_fn
    from openai import AzureOpenAI, OpenAI

    from app.config import (
        AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_CHAT_DEPLOYMENT,
        AZURE_OPENAI_ENDPOINT, OPENAI_API_KEY, OPENAI_MODEL,
    )
    from app.errors import ConfigError

    with _clients_lock:
        if _chat_fn is not None:
            return _chat_fn
        azure = None
        if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_CHAT_DEPLOYMENT:
            # max_retries=0: the SDK's retry-on-timeout would multiply every deadline.
            azure = AzureOpenAI(azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY,
                                api_version=AZURE_OPENAI_API_VERSION, max_retries=0)
        direct = OpenAI(api_key=OPENAI_API_KEY, max_retries=0) if OPENAI_API_KEY else None
        if azure is None and direct is None:
            raise ConfigError("[openai] no OpenAI/Azure credentials configured")
        _chat_fn = make_chat_completion_fn(
            openai_client=direct or azure, azure_openai_client=azure,
            openai_model=OPENAI_MODEL, azure_chat_deployment=AZURE_OPENAI_CHAT_DEPLOYMENT)
        return _chat_fn


def openai_direct_client() -> Any:
    """OpenAI with its own key and a deadline, or None without a key."""
    global _direct_client
    if _direct_client is None:
        from app.config import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            return None
        from openai import OpenAI
        _direct_client = OpenAI(api_key=OPENAI_API_KEY, max_retries=0,
                                timeout=DEFAULT_CHAT_TIMEOUT_S)
    return _direct_client
