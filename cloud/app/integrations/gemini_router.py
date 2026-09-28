"""Optional Gemini router backend (tried before Bedrock/Azure), enabled by GEMINI_ROUTER_MODEL."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

_MODEL_ID = os.getenv("GEMINI_ROUTER_MODEL", "").strip()
_MAX_TOKENS = int(os.getenv("GEMINI_ROUTER_MAX_TOKENS", "700"))
_TIMEOUT_MS = int(float(os.getenv("GEMINI_ROUTER_TIMEOUT_S", "12")) * 1000)

_client = None


def gemini_enabled() -> bool:
    return bool(_MODEL_ID and GEMINI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
        )
    return _client


def _to_gemini_tools(specs: List[Dict[str, Any]]):
    from google.genai import types

    decls = []
    seen = set()
    for d in specs:
        name = d.get("name")
        if not name or name in seen:
            continue  # duplicate names are rejected
        seen.add(name)
        params = d.get("parameters") or {"type": "object", "properties": {}}
        decls.append(types.FunctionDeclaration(
            name=name,
            description=d.get("description") or name,
            parameters_json_schema=params,
        ))
    return types.Tool(function_declarations=decls)


def route_with_gemini(
    system: str, user: str, specs: List[Dict[str, Any]]
) -> Optional[List[Dict[str, Any]]]:
    """List of {name, args} ([] = chat), or None on failure (→ next backend)."""
    try:
        from google.genai import types

        client = _get_client()
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[_to_gemini_tools(specs)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO,
                )
            ),
            temperature=0,
            max_output_tokens=_MAX_TOKENS,
        )
        _t = time.perf_counter()
        resp = client.models.generate_content(
            model=_MODEL_ID, contents=user, config=config,
        )
        logger.info(
            f"[gemini_router] routing: {(time.perf_counter()-_t)*1000:.0f}ms"
        )

        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            return []
        parts = (getattr(candidates[0].content, "parts", None) or [])
        calls: List[Dict[str, Any]] = []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                calls.append({"name": str(fc.name), "args": fc.args or {}})
        return calls
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[gemini_router] failed, falling back: {exc}")
        return None
