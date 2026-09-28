"""Optional Bedrock Converse router backend, enabled by BEDROCK_ROUTER_MODEL_ID.

Auth: AWS_BEARER_TOKEN_BEDROCK (read by boto3).
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
    return bool(_MODEL_ID)


def _get_client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        # boto3 defaults (60s + retries) exceed Heroku's 30s request cut.
        _client = boto3.client(
            "bedrock-runtime", region_name=_REGION,
            config=Config(connect_timeout=3, read_timeout=12,
                          retries={"max_attempts": 1}),
        )
    return _client


def _to_tool_config(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    tools = []
    seen = set()
    for d in specs:
        name = d.get("name")
        if not name or name in seen:
            continue  # Bedrock rejects duplicate tool names (meta vs registered)
        seen.add(name)
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
    """List of {name, args} ([] = chat), or None on failure (→ Azure)."""
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
        return calls
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[bedrock_router] failed, falling back to Azure: {exc}")
        return None
