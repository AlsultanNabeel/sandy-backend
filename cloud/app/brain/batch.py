"""Azure's batch jobs, at about half the price, for scheduled work only.

Off unless `SANDY_BATCH_DEPLOYMENT` names a Global Batch deployment, and only for a priority
that may wait (`background.may_batch`: a task's steps, never what the user waits on). A task
that is not urgent submits its model step here and collects the answer on a later run
(`task_runner`); Azure answers within its window (`WINDOW`), usually much sooner.

`submit` uploads one request as a JSONL file and starts the job; `collect` is None while it
runs, the answer's text once it is done (its tokens into the current trace, priced at the
model's ordinary rate though a batch costs about half), and raises when the job failed or
expired. Both are called by `background` alone (`call` with ``as_batch``, `collect`), the one
place a limit on model calls goes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.brain import background
from app.features import trace_store

logger = logging.getLogger(__name__)

WINDOW = "24h"
_client: Any = None


def deployment() -> str:
    return os.getenv("SANDY_BATCH_DEPLOYMENT", "").strip()


def enabled(priority: str) -> bool:
    return background.may_batch(priority) and bool(deployment())


def _azure() -> Any:
    global _client
    if _client is None:
        from openai import AzureOpenAI

        from app import config
        _client = AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
                              api_key=config.AZURE_OPENAI_API_KEY,
                              api_version=config.AZURE_OPENAI_API_VERSION, max_retries=0)
    return _client


def submit(what: str, messages: List[Dict[str, Any]], *, max_tokens: int,
           temperature: float) -> str:
    """The started job's id."""
    line = {"custom_id": what, "method": "POST", "url": "/chat/completions",
            "body": {"model": deployment(), "messages": messages, "max_tokens": max_tokens,
                     "temperature": temperature}}
    client = _azure()
    upload = client.files.create(file=(f"{what}.jsonl", json.dumps(line, ensure_ascii=False).encode()),
                                 purpose="batch")
    job = client.batches.create(input_file_id=upload.id, endpoint="/chat/completions",
                                completion_window=WINDOW)
    logger.info("[batch] %s submitted as %s", what, job.id)
    return job.id


def collect(job_id: str) -> Optional[str]:
    """The answer's text once the job is done; None while it runs."""
    client = _azure()
    job = client.batches.retrieve(job_id)
    if job.status in ("failed", "expired", "cancelled"):
        raise RuntimeError(f"batch {job_id} {job.status}")
    if job.status != "completed" or not job.output_file_id:
        return None
    first = client.files.content(job.output_file_id).text.strip().splitlines()[0]
    body = json.loads(first)["response"]["body"]
    usage = body.get("usage") or {}
    trace_store.note_model_call("azure_batch", str(body.get("model") or deployment()),
                                tokens_in=int(usage.get("prompt_tokens") or 0),
                                tokens_out=int(usage.get("completion_tokens") or 0))
    return (body["choices"][0]["message"].get("content") or "").strip()
