"""An expense's category from its words, when nobody picked one.

«شريت كولا بعشرين شيكل» is food, not "other": the app and Sandy may leave the
category out, and this fills it in the background, so saving never waits on it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.blocks import entries
from app.utils.thread_pool import submit_background

logger = logging.getLogger(__name__)

CATEGORIES = ("food", "transport", "shopping", "bills", "fun", "health", "other")

_PROMPT = (
    "Classify this expense into exactly one category and answer with the word only: "
    "food (any food or drink, groceries, restaurants, coffee, snacks), transport (taxi, bus, "
    "fuel, parking, tickets for travel), shopping (clothes, electronics, things for the home), "
    "bills (rent, internet, phone, electricity, subscriptions), fun (games, cinema, outings, "
    "gifts), health (pharmacy, doctor, gym), other."
)


def classify(text: str) -> str:
    """One of CATEGORIES; "other" when the model is not reachable or unsure."""
    from openai import OpenAIError

    from app.errors import ConfigError
    from app.integrations.openai_client import chat_fn

    try:
        resp = chat_fn()(messages=[{"role": "system", "content": _PROMPT},
                                   {"role": "user", "content": text[:300]}],
                         max_tokens=4, temperature=0)
        word = (resp.choices[0].message.content or "").strip().lower().strip(".")
    except (OpenAIError, ConfigError) as exc:  # no model: "other" is a fine answer
        logger.warning("[categorize] failed: %s", exc)
        return "other"
    return word if word in CATEGORIES else "other"


def _fill(entry_id: str, text: str) -> None:
    row = entries.get(entry_id)
    if not row or (row.get("data") or {}).get("category"):
        return  # gone, or picked meanwhile
    data: Dict[str, Any] = dict(row.get("data") or {})
    data["category"] = classify(text)
    entries.update(entry_id, data=data, embed=False)


def categorize_later(entry_id: str, kind: str, text: str,
                     data: Optional[Dict[str, Any]]) -> None:
    """An expense saved with no category gets one, in the caller's tenant, off the request."""
    if kind != "expense" or not entry_id or (data or {}).get("category"):
        return
    submit_background(_fill, entry_id, text, _label="categorize")
