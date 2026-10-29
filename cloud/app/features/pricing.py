"""What a model call costs: the one place the prices live.

US dollars per million tokens, as each provider publishes them: ``in`` for the prompt,
``cached`` for the part of the prompt the provider served from its cache, ``out`` for the
answer. Change a price here and move ``PRICES_UPDATED`` with it. A name is matched whole,
then by the longest name it starts with (a dated deployment, «gpt-4.1-2025-04-14», is
priced as «gpt-4.1»). A model not listed costs nothing and is logged once.

The live voice models are priced at their audio rates: a call is mostly audio.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Optional

logger = logging.getLogger(__name__)

PRICES_UPDATED = date(2026, 10, 29)

PRICES: Dict[str, Dict[str, float]] = {
    "gpt-4.1": {"in": 2.00, "cached": 0.50, "out": 8.00},
    "gpt-4.1-mini": {"in": 0.40, "cached": 0.10, "out": 1.60},
    "gpt-4.1-nano": {"in": 0.10, "cached": 0.025, "out": 0.40},
    "gpt-4o": {"in": 2.50, "cached": 1.25, "out": 10.00},
    "gpt-4o-mini": {"in": 0.15, "cached": 0.075, "out": 0.60},
    # Azure Global Standard, read from an outside page, not Microsoft's (see UNCONFIRMED).
    "gpt-6-luna": {"in": 0.10, "cached": 0.01, "out": 0.50},
    "gemini-2.5-flash-native-audio": {"in": 3.00, "cached": 0.75, "out": 12.00},
    "gemini-3.1-flash-live": {"in": 3.00, "cached": 0.75, "out": 12.00},
}

# Prices taken from an outside source, not the provider's own: each must be checked against
# the first official Azure invoice that bills it, then taken off this list.
UNCONFIRMED: Dict[str, str] = {
    "gpt-6-luna": "azurespeed.com/AzureAiModelPricing/Models/openai-gpt-6-luna, 29 Oct 2026",
}

_unpriced_seen: set = set()


def price_of(model: str) -> Optional[Dict[str, float]]:
    name = (model or "").strip().lower().removeprefix("models/")
    if name in PRICES:
        return PRICES[name]
    starts = [k for k in PRICES if name.startswith(k)]
    return PRICES[max(starts, key=len)] if starts else None


def cost(model: str, *, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float:
    price = price_of(model)
    if price is None:
        if model not in _unpriced_seen:
            _unpriced_seen.add(model)
            logger.warning("[pricing] no price for model %r — counted as free", model)
        return 0.0
    cached = min(max(tokens_cached, 0), max(tokens_in, 0))
    return ((tokens_in - cached) * price["in"] + cached * price["cached"]
            + tokens_out * price["out"]) / 1_000_000
