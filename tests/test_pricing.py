"""Model prices (`features/pricing.py`): one place, with the date they were last checked."""
from __future__ import annotations

from datetime import date

from app.features import pricing


def test_prices_carry_the_date_they_were_last_checked():
    assert isinstance(pricing.PRICES_UPDATED, date)
    assert pricing.PRICES, "no prices"
    for name, p in pricing.PRICES.items():
        assert set(p) == {"in", "out", "cached"}, name


def test_cost_per_million_tokens():
    pricing.PRICES["test-model"] = {"in": 2.0, "out": 8.0, "cached": 0.5}
    try:
        # 1M in (of which 200k cached) and 100k out
        usd = pricing.cost("test-model", tokens_in=1_000_000, tokens_out=100_000,
                           tokens_cached=200_000)
        assert round(usd, 6) == round(0.8 * 2.0 + 0.2 * 0.5 + 0.1 * 8.0, 6)
    finally:
        del pricing.PRICES["test-model"]


def test_a_dated_deployment_name_finds_its_model():
    assert pricing.price_of("gpt-4.1-2025-04-14") == pricing.PRICES["gpt-4.1"]


def test_an_unknown_model_costs_nothing_and_never_raises():
    assert pricing.cost("no-such-model", tokens_in=10, tokens_out=10) == 0.0
