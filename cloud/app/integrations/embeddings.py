"""Text embeddings: Azure when an embedding deployment is configured, else OpenAI direct.

`embed()` is the repo's one door to a vector; None when embeddings are off or fail,
and every caller then falls back to text search.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
# The SDK default is ten minutes with retries; a stalled endpoint must give the caller back.
EMBED_TIMEOUT_S = 8.0

_client: Any = None
_model = EMBEDDING_MODEL
_built = False
_lock = threading.Lock()


def _get_client() -> Any:
    """Built once (C4); None with no key."""
    global _client, _model, _built
    if _built:
        return _client
    with _lock:
        if _built:
            return _client
        from app.config import (
            AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION,
            AZURE_OPENAI_EMBEDDING_DEPLOYMENT, AZURE_OPENAI_ENDPOINT, OPENAI_API_KEY,
        )
        if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_EMBEDDING_DEPLOYMENT:
            from openai import AzureOpenAI
            _client = AzureOpenAI(api_key=AZURE_OPENAI_API_KEY, api_version=AZURE_OPENAI_API_VERSION,
                                  azure_endpoint=AZURE_OPENAI_ENDPOINT, max_retries=0)
            _model = AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        elif OPENAI_API_KEY:
            from openai import OpenAI
            _client = OpenAI(api_key=OPENAI_API_KEY, max_retries=0)
            _model = EMBEDDING_MODEL
        _built = True
        return _client


def embed(text: str) -> Optional[List[float]]:
    client = _get_client()
    if client is None or not text:
        return None
    try:
        resp = client.embeddings.create(model=_model, input=[text], timeout=EMBED_TIMEOUT_S)
        return resp.data[0].embedding if resp.data else None
    except Exception as exc:  # noqa: BLE001 — provider boundary; text search is the floor
        logger.warning("[embeddings] embedding failed: %s", exc)
        return None
