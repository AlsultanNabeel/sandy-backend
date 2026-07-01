"""Bedrock Converse routing — an alternative router backend to Azure.

Enabled when ``BEDROCK_ROUTER_MODEL_ID`` is set. Uses the Converse API's unified
tool-use, so any Bedrock model (e.g. Qwen3) routes with the same tool specs the
Azure path uses. Auth is the Bedrock API key in ``AWS_BEARER_TOKEN_BEDROCK``,
which boto3 reads on its own.

Returns a list of {name, args} calls (empty = the model chose to chat), or None
to signal the caller to fall back to the Azure router.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MODEL_ID = os.getenv("BEDROCK_ROUTER_MODEL_ID", "").strip()
_REGION = os.getenv("AWS_REGION", "us-east-1").strip()
_MAX_TOKENS = int(os.getenv("BEDROCK_ROUTER_MAX_TOKENS", "700"))

_client = None


def bedrock_enabled() -> bool:
    """True when a Bedrock router model is configured."""
    return bool(_MODEL_ID)


def _get_client():
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("bedrock-runtime", region_name=_REGION)
    return _client


def _to_tool_config(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert our name/description/JSON-Schema specs to Converse toolConfig."""
    tools = []
    for d in specs:
        name = d.get("name")
        if not name:
            continue
        params = d.get("parameters") or {"type": "object", "properties": {}}
        tools.append({
            "toolSpec": {
                "name": name,
                "description": d.get("description") or name,
                "inputSchema": {"json": params},
            }
        })
    return {"tools": tools}


def route_with_bedrock(
    system: str, user: str, specs: List[Dict[str, Any]]
) -> Optional[List[Dict[str, Any]]]:
    """Route one turn through Bedrock Converse. None on failure (→ Azure)."""
    try:
        client = _get_client()
        _t = time.perf_counter()
        resp = client.converse(
            modelId=_MODEL_ID,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            toolConfig=_to_tool_config(specs),
            inferenceConfig={"maxTokens": _MAX_TOKENS, "temperature": 0},
        )
        logger.info(
            f"[bedrock_router] routing: {(time.perf_counter()-_t)*1000:.0f}ms"
        )
        blocks = (
            (resp.get("output", {}) or {}).get("message", {}) or {}
        ).get("content", []) or []
        calls: List[Dict[str, Any]] = []
        for block in blocks:
            tool_use = block.get("toolUse") if isinstance(block, dict) else None
            if tool_use and tool_use.get("name"):
                calls.append({
                    "name": str(tool_use["name"]),
                    "args": tool_use.get("input") or {},
                })
        return calls  # empty list = model replied as chat (no tool)
    except Exception as exc:  # noqa: BLE001 — any failure falls back to Azure
        logger.error(f"[bedrock_router] failed, falling back to Azure: {exc}")
        return None
