"""Azure OpenAI adapter for intent routing (FC mode) — يحلّ محل GeminiFlashClient.

يستخدم Azure GPT-4o-mini مع JSON mode، بنفس الواجهة العامة للـ GeminiFlashClient
ليكون الاستبدال drop-in في maestro.py و gift_tools.py.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

# Routing can run on its own fast/cheap deployment (e.g. Azure model-router or a
# mini model). Falls back to the full chat deployment when unset, so behaviour is
# unchanged until AZURE_OPENAI_ROUTER_DEPLOYMENT is provided.
DEFAULT_AZURE_INTENT_DEPLOYMENT = (
    os.getenv("AZURE_OPENAI_ROUTER_DEPLOYMENT", "").strip()
    or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "sandy-chat")
)

# Per-request timeout (seconds) so a hung intent/router call fails fast into the
# existing fallbacks instead of blocking the whole turn. Upper bound for hangs,
# not a latency target — intent calls normally return in <2s.
AZURE_INTENT_TIMEOUT_S = float(os.getenv("AZURE_INTENT_TIMEOUT_S", "12"))

# Singleton client — يُبنى مرة واحدة عند أول استدعاء ويُعاد استخدامه.
# منع memory leak من إنشاء AzureOpenAI client + httpx pool كل رسالة.
_CACHED_AZURE_CLIENT: Any = None
_CACHED_CLIENT_KEY: tuple = ()


def _get_azure_client(api_key: str, api_version: str, endpoint: str) -> Any:
    """يعيد client مُخزّن أو يبنيه أول مرة."""
    global _CACHED_AZURE_CLIENT, _CACHED_CLIENT_KEY
    key = (api_key, api_version, endpoint)
    if _CACHED_AZURE_CLIENT is not None and _CACHED_CLIENT_KEY == key:
        return _CACHED_AZURE_CLIENT

    from openai import AzureOpenAI
    AzureOpenAICls = AzureOpenAI

    _CACHED_AZURE_CLIENT = AzureOpenAICls(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )
    _CACHED_CLIENT_KEY = key
    return _CACHED_AZURE_CLIENT


# Params a model may reject; scanned by name so we never mis-read 'error' (the
# dict key in the error repr) as the offending parameter.
_TUNABLE_PARAMS = (
    "max_tokens", "max_completion_tokens", "temperature", "top_p",
    "frequency_penalty", "presence_penalty", "logprobs", "tool_choice",
)


def _rejected_param(exc: Exception) -> Optional[str]:
    """Pull the offending parameter name out of an Azure 400 error."""
    param = getattr(exc, "param", None)
    if param:
        return str(param)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        param = (err.get("param") if isinstance(err, dict) else None) or body.get("param")
        if param:
            return str(param)
    # Last resort: scan the message for a known tunable param, not any quoted word.
    msg = str(exc)
    for name in _TUNABLE_PARAMS:
        if f"'{name}'" in msg:
            return name
    return None


def _create_chat_resilient(client: Any, kwargs: Dict[str, Any]) -> Any:
    """create() that adapts to per-model parameter quirks.

    gpt-5 / o-series reject ``max_tokens`` (want ``max_completion_tokens``) and a
    fixed ``temperature``; older models want ``max_tokens``. Try the call, and on
    an unsupported-parameter 400 remap or drop that one param and retry, so the
    same code works across deployments without a config flag.
    """
    kwargs = dict(kwargs)
    _protected = {"model", "messages", "tools"}
    for _ in range(4):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            param = _rejected_param(exc)
            if param == "max_tokens" and "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                continue
            if param and param in kwargs and param not in _protected:
                kwargs.pop(param)
                continue
            raise
    return client.chat.completions.create(**kwargs)


def _log_azure_usage(response: Any) -> None:
    """Log token usage + cache hit + est cost (no message text) for Heroku logs.

    R3: Azure auto-caches stable prompt prefixes ≥1024 tokens, billed at half.
    Keeping the big tool/persona prefix first is what lets cached_tokens stay high.
    """
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
    if cached:
        pct = (cached / in_tok * 100) if in_tok else 0
        print(
            f"[Azure] in={in_tok} (cached={cached} {pct:.0f}%) "
            f"out={out_tok} ~${cost:.5f}",
            flush=True,
        )
    else:
        print(f"[Azure] in={in_tok} out={out_tok} ~${cost:.5f}", flush=True)


class AzureIntentClient:
    """Azure OpenAI adapter لتحليل النية وعمليات JSON-mode الأخرى.

    واجهة متوافقة مع GeminiFlashClient القديمة:
    - ``_generate_with_gemini(prompt, response_mime_type, system_instruction, ...)``
        احتُفظ بالاسم رغم أنه Azure الآن — لتقليل تغييرات الـ call sites.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        model: Any = None,
    ):
        self.api_key = (
            api_key if api_key is not None else os.getenv("AZURE_OPENAI_API_KEY", "")
        ).strip()
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview").strip()
        self.model_name = (
            model_name if model_name is not None else DEFAULT_AZURE_INTENT_DEPLOYMENT
        ).strip()
        self._model = model  # for test mocks

    def generate_text(self, prompt: str, **kwargs) -> str:
        """Public one-shot text generation. New code should call this instead of
        the legacy ``_generate_with_gemini`` name (kept for backward compat)."""
        return self._generate_with_gemini(prompt, **kwargs)

    def _generate_with_gemini(
        self,
        prompt: str,
        *,
        response_mime_type: str | None = None,
        max_output_tokens: int | None = None,
        system_instruction: str | None = None,
        temperature: float | None = None,
        response_schema: dict | None = None,
    ) -> str:
        """يولّد ردّ من Azure OpenAI — اسم الميثود مُحتفظ به للتوافق الخلفي.

        - ``response_mime_type='application/json'`` → JSON mode عبر response_format
        - ``system_instruction`` → system role message
        - ``response_schema`` يُتجاهل (gpt-4o-mini يستخدم json_object العام)
        """
        if self._model:
            # test mock — يحاكي السلوك القديم
            response = self._model.generate_content(prompt)
            text = getattr(response, "text", None)
            return str(text).strip() if text else ""

        if not (self.api_key and self.endpoint):
            raise RuntimeError(
                "Azure OpenAI not configured: AZURE_OPENAI_API_KEY/ENDPOINT missing"
            )

        try:
            client = _get_azure_client(self.api_key, self.api_version, self.endpoint)
        except ImportError as exc:
            raise RuntimeError(
                "openai package required: pip install openai"
            ) from exc

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0,
            "max_tokens": max_output_tokens or 600,
            # Fail fast on a hung upstream — openai SDK supports per-request timeout.
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
        """Native function-calling: the model either calls one/more tools or
        replies in plain text. Returns the raw message object (``.content`` +
        ``.tool_calls``), or None on failure.

        ``system`` is the stable prefix (persona + rules) and ``tools`` the stable
        catalog — both come first so Azure prompt caching keeps biting; only the
        per-turn ``user`` block varies.
        """
        if self._model:  # test mock — no native tool support, signal fallback
            return None
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
            "timeout": AZURE_INTENT_TIMEOUT_S,
        })
        _log_azure_usage(response)
        choice = response.choices[0] if response.choices else None
        return choice.message if choice else None
