"""Exa search client behind a circuit breaker."""

import logging
from typing import Any, Dict, List

import requests

from app.utils.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

_cb = CircuitBreaker(name="exa", failure_threshold=5, recovery_timeout=60.0)


def _do_search(
    query: str, exa_api_key: str, num_results: int, timeout: int
) -> List[Dict[str, Any]]:
    url = "https://api.exa.ai/search"
    headers = {"x-api-key": exa_api_key, "Content-Type": "application/json"}
    payload = {
        "query": query,
        "numResults": num_results,
        "type": "auto",
        "contents": {"text": True},
    }
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    results = []
    for item in data.get("results", []):
        results.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "text": str(item.get("text") or "").strip(),
                "published_date": str(item.get("publishedDate") or "").strip(),
            }
        )
    return results


# For the /api/research route; a chat turn's web search keeps the 60s default.
INTERACTIVE_TIMEOUT_S = 15


def search_exa(
    query: str,
    exa_api_key: str,
    num_results: int = 10,
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    if not exa_api_key:
        logger.warning("[Exa] EXA_API_KEY missing")
        return []
    try:
        results = _cb.call(_do_search, query, exa_api_key, num_results, timeout)
        logger.info("[Exa] found %d results", len(results))
        return results
    except CircuitOpenError:
        logger.warning("[Exa] circuit open, skipping search")
        return []
    except Exception as e:
        logger.error("[Exa] search failed: %s", e)
        return []
