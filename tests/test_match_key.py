"""Pure-logic guards for row-name matching.

match_key is the normaliser every "which one did they mean" lookup compares against.
"""
from app.brain.matching import match_key as _task_match_key


def test_match_key_normalises_alef_variants():
    assert _task_match_key("أحمد") == _task_match_key("احمد")
    assert _task_match_key("إشترِ") == _task_match_key("اشتر")


def test_match_key_normalises_ya_and_ta_marbuta():
    assert _task_match_key("اشترى") == _task_match_key("اشتري")
    assert _task_match_key("مدرسة") == _task_match_key("مدرسه")


def test_match_key_maps_arabic_digits_and_strips_diacritics():
    assert "5" in _task_match_key("مهمة ٥")
    assert _task_match_key("مُهِمّ") == _task_match_key("مهم")
