"""The kinds table: lookups, prefix rows, and data validation."""
from datetime import datetime, timezone

import pytest

from app.blocks import kinds
from app.blocks.kinds import LIST, LOG, SCHEDULE, KindError, validate


def test_every_row_is_complete_and_unique():
    seen = set()
    for k in kinds.KINDS:
        assert k.block in kinds.BLOCKS
        assert k.name and k.ar and k.en and k.icon
        assert (k.block, k.name) not in seen
        seen.add((k.block, k.name))


def test_the_provisional_names_are_all_declared():
    assert set(kinds.names(LOG)) >= {"fact", "reading", "expense", "habit", "mood",
                                     "journal", "health", "photo", "note", "summary"}
    assert set(kinds.names(LIST)) >= {"tasks", "shopping", "goals", "reading", "habits"}
    assert set(kinds.names(SCHEDULE)) == {"reminder", "message_to_future_self", "scene",
                                          "daily_nudge", "summary_nudge"}


def test_valid_data_passes_and_int_counts_as_float():
    assert validate(LOG, "expense", {"amount": 12, "category": "food"}) == {
        "amount": 12, "category": "food"}
    assert validate(LOG, "note") == {}
    assert validate(LOG, "expense", {"amount": None}) == {"amount": None}


def test_unknown_kind_is_refused():
    with pytest.raises(KindError):
        validate(LOG, "gift", {})
    with pytest.raises(KindError):
        validate(LIST, "fact", {})  # a log kind is not a list


def test_undeclared_field_is_refused():
    with pytest.raises(KindError):
        validate(LOG, "expense", {"amount": 1, "colour": "red"})


def test_wrong_type_is_refused_and_bool_is_not_a_number():
    with pytest.raises(KindError):
        validate(LOG, "expense", {"amount": "12"})
    with pytest.raises(KindError):
        validate(LOG, "expense", {"amount": True})
    with pytest.raises(KindError):
        validate(SCHEDULE, "reminder", {"sent_at": "2026-01-01"})
    assert validate(SCHEDULE, "reminder", {"sent_at": datetime.now(timezone.utc)})


def test_project_lists_match_the_prefix_row_only_with_a_name():
    assert validate(LIST, "project:kitchen", {}) == {}
    assert kinds.get_kind(LIST, "project:kitchen").en == "Project"
    with pytest.raises(KindError):
        validate(LIST, "project:", {})
    with pytest.raises(KindError):
        validate(LIST, "project:kitchen", {"anything": 1})
