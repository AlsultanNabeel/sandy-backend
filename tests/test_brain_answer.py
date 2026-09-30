"""The yes/no resolver a held action waits on, on chat and voice alike."""

import pytest

from app.brain.confirm import answer


@pytest.mark.parametrize("text", ["اه", "نعم", "ok", "تمام", "آه", "اه.", "اه 👍", "اه صح", "اه احذفها"])
def test_a_yes(text):
    assert answer(text) == "yes"


@pytest.mark.parametrize("text", ["لا", "no", "cancel", "الغ", "لا تحذف", "انسى", "اه بس لا"])
def test_a_no(text):
    assert answer(text) == "no"


@pytest.mark.parametrize("text", ["", "بكرا الساعة 3", "اي شي", "اه بس خليني افكر فيها شوي كمان",
                                  "حكالي لا تحذف الملف بس انا ما سمعت"])
def test_neither(text):
    """Ambiguous leads confirm only alone; a long reply is a new message, not an answer."""
    assert answer(text) == "other"
