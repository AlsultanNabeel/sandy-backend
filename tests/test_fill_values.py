"""A fill writes and picks only what he said (`brain/fill_values.py`): his values are read from
his own words by code (his messages, his name when he says «اسمي», never the model's), and
every value typed, every box ticked and every option picked is checked against them before it
is done. A value he did not give is refused, and he is asked; a choice of his is never typed
into a text field («نبيل لارج», the size in the name, on 4 Nov 2026); a value is his only as he
said it, never one that looks like it. The question before sending shows every field with its
value and says which required one is empty. In both languages."""
from __future__ import annotations

import pytest

from app.brain import fill_values as FV
from app.brain import lang

CHOICES = ["Small", "Medium", "Large", "Bacon", "Extra Cheese", "Onion", "Mushroom"]
NAME = {"label": "Customer name", "name": "custname", "type": "text", "choices": CHOICES}
PHONE = {"label": "Telephone", "name": "custtel", "type": "tel", "choices": CHOICES}
EMAIL = {"label": "E-mail address", "name": "custemail", "type": "email", "choices": CHOICES}
NOTES = {"label": "Delivery instructions", "name": "comments", "type": "textarea", "choices": CHOICES}


def _values(*said, name="نبيل"):
    return FV.his_values(list(said), preferred_name=name)


# ── Only his name ──

def test_with_only_his_name_only_his_name_is_written():
    values = _values("حطي اسمي")
    assert FV.vet_type(values, "نبيل", NAME) is None
    assert FV.vet_type(values, "123-456-7890", PHONE) == FV.NOT_HIS
    assert FV.vet_type(values, "n@example.com", EMAIL) == FV.NOT_HIS
    for option in ("Large", "Medium", "Bacon", "Mushroom"):
        assert FV.vet_choose(values, option, checked=False) == FV.NOT_HIS


def test_his_name_is_his_only_when_he_names_it():
    assert FV.vet_type(_values("عبّي النموذج"), "نبيل", NAME) == FV.NOT_HIS
    assert FV.vet_type(_values("fill it with my name"), "نبيل", NAME) is None


# ── A choice of his is picked, never typed («نبيل لارج») ──

def test_the_size_he_said_is_picked_and_never_written_into_his_name():
    values = _values("حطي اسمي ولارج")
    assert FV.vet_choose(values, "Large", checked=False) is None
    assert FV.vet_type(values, "نبيل لارج", NAME) == FV.NOT_HIS
    assert FV.vet_type(values, "لارج", NAME) == FV.A_CHOICE
    assert FV.vet_choose(values, "Medium", checked=False) == FV.NOT_HIS
    assert FV.vet_type(values, "نبيل", NAME) is None


def test_a_value_is_never_written_into_a_field_of_another_kind():
    values = _values("fill the form: name Nabeel, email n@example.com, phone 0599 123 456")
    assert FV.vet_type(values, "Nabeel", NAME) is None
    assert FV.vet_type(values, "n@example.com", EMAIL) is None
    assert FV.vet_type(values, "0599 123 456", PHONE) is None
    assert FV.vet_type(values, "n@example.com", NAME) == FV.WRONG_FIELD
    assert FV.vet_type(values, "Nabeel", PHONE) == FV.WRONG_FIELD
    assert FV.vet_type(values, "0599 123 456", NAME) == FV.WRONG_FIELD


# ── In English ──

def test_an_english_request_fills_what_it_says_and_picks_what_it_names():
    values = _values("Fill https://httpbin.org/forms/post with name Nabeel, size medium and onion")
    assert FV.vet_type(values, "Nabeel", NAME) is None
    assert FV.vet_choose(values, "Medium", checked=False) is None
    assert FV.vet_choose(values, "Onion", checked=False) is None
    assert FV.vet_choose(values, "Bacon", checked=False) == FV.NOT_HIS
    assert FV.vet_type(values, "Please ring the bell", NOTES) == FV.NOT_HIS


def test_pairs_he_writes_are_his_values():
    values = _values("الاسم: نبيل، الهاتف: 0599123456، ملاحظات: اتصل قبل ما توصل")
    assert FV.vet_type(values, "نبيل", NAME) is None
    assert FV.vet_type(values, "0599123456", PHONE) is None
    assert FV.vet_type(values, "اتصل قبل ما توصل", NOTES) is None


# ── A value that looks like his is not his ──

@pytest.mark.parametrize("said, typed, field", [
    ("الاسم نبيل", "Nabeel", NAME), ("name Nabeel", "Nabeel Smith", NAME),
    ("phone 0599123456", "059912345", PHONE), ("phone 0599123456", "05991234567", PHONE)])
def test_a_value_that_only_looks_like_his_is_refused(said, typed, field):
    assert FV.vet_type(_values(said), typed, field) == FV.NOT_HIS


def test_an_option_that_only_contains_his_is_refused():
    values = _values("size large")
    assert FV.vet_choose(values, "Large", checked=False) is None
    assert FV.vet_choose(values, "Extra Large", checked=False) == FV.NOT_HIS


def test_an_arabic_word_picks_its_option_in_the_other_script():
    values = _values("بدي ميديوم مع بيكون")
    assert FV.vet_choose(values, "Medium", checked=False) is None
    assert FV.vet_choose(values, "Bacon", checked=False) is None
    assert FV.vet_choose(values, "Mushroom", checked=False) == FV.NOT_HIS


def test_unticking_or_clearing_takes_nothing_of_his():
    values = _values("حطي اسمي")
    assert FV.vet_choose(values, "Bacon", checked=True) is None
    assert FV.vet_type(values, "", NAME) is None


def test_the_models_own_words_are_never_his():
    # The model's «details» never reach his values: only his messages and his name.
    values = FV.his_values(["عبي"], preferred_name="نبيل")
    assert FV.vet_type(values, "لارج", NAME) == FV.NOT_HIS


# ── The question before sending ──

FIELDS = [{"field": "Customer name", "value": "نبيل", "required": True},
          {"field": "Telephone", "value": "", "required": True},
          {"field": "E-mail address", "value": "", "required": False},
          {"field": "Pizza Size", "value": "Large", "required": False}]


@pytest.mark.parametrize("language, empty, required", [("ar", "فاضي", "فاضي وهو مطلوب"),
                                                        ("en", "empty", "empty, and it is required")])
def test_the_question_shows_every_field_and_which_required_one_is_empty(language, empty, required):
    with lang.using(language):
        said = FV.summary(FIELDS)
    assert "Customer name: نبيل" in said and "Pizza Size: Large" in said
    assert f"Telephone: {required}" in said and f"E-mail address: {empty}" in said


@pytest.mark.parametrize("language, words", [("ar", "ما كتبت"), ("en", "I didn't write")])
def test_what_she_would_have_invented_is_asked_in_his_language(language, words):
    with lang.using(language):
        said = FV.asked([{"field": "Telephone", "why": FV.NOT_HIS}, {"field": "Customer name", "why": FV.A_CHOICE}])
    assert words in said and "Telephone" in said and "Customer name" in said
