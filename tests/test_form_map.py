"""The fast path of a fill (`brain/form_map.py`): the code reads a form's fields once (key, label,
kind, options, required) from the page as the browser drew it; the model's table of which of his
values goes where is checked by the code (every value his, every choice one of that field's own
options and his, a required field left empty asked); a form in steps, with controls of its own or
several forms goes to the agent. Saved forms: httpbin's, an Arabic one, an English one, one with
required fields he did not give, one in steps, and one whose choice shows a field."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.brain import fill_values, form_map

FORMS = Path(__file__).parent / "fixtures" / "forms"


def _read(name):
    return form_map.read((FORMS / name).read_text(encoding="utf-8"))


def _his(*said, name=""):
    return fill_values.his_values(list(said), name)


def test_httpbins_form_is_read_once_with_every_field():
    form = _read("httpbin.html")
    assert form["form"] == 0 and form["hard"] == ""
    by = {f["key"]: f for f in form["fields"]}
    assert list(by) == ["custname", "custtel", "custemail", "size", "topping", "delivery", "comments"]
    assert by["custname"]["label"] == "Customer name" and by["custtel"]["kind"] == "tel"
    assert by["size"]["kind"] == "radio" and by["size"]["label"] == "Pizza Size"
    assert by["size"]["options"] == ["Small", "Medium", "Large"] and not by["size"]["multiple"]
    assert by["topping"]["multiple"] and "Extra Cheese" in by["topping"]["options"]
    assert by["comments"]["kind"] == "textarea" and by["delivery"]["kind"] == "time"
    assert form_map.button_label((FORMS / "httpbin.html").read_text(), 0) == "Submit order"


def test_an_arabic_form_is_read_with_its_own_labels_and_options():
    form = _read("form_ar.html")
    by = {f["key"]: f for f in form["fields"]}
    assert form["hard"] == "" and "token" not in by
    assert by["fullname"]["label"] == "الاسم الكامل" and by["fullname"]["required"]
    assert by["city"]["options"] == ["القاهرة", "الجيزة", "الإسكندرية"] and by["city"]["values"][0] == "cairo"
    assert by["shift"]["options"] == ["صباحي", "مسائي"] and by["shift"]["label"] == "الدوام"


def test_an_english_form_beside_an_empty_one_is_the_one_read():
    form = _read("form_en.html")
    assert form["form"] == 0 and form["hard"] == ""
    assert [f["key"] for f in form["fields"]] == ["first_name", "email", "role", "news"]


@pytest.mark.parametrize("name, why", [("form_steps.html", "own_controls")])
def test_a_form_in_steps_or_of_its_own_controls_goes_to_the_agent(name, why):
    assert _read(name)["hard"] == why


def test_a_form_whose_only_way_on_is_next_goes_to_the_agent():
    page = (FORMS / "form_steps.html").read_text().replace(
        '<div role="combobox" aria-label="Country" tabindex="0">Pick a country</div>', "")
    assert form_map.read(page)["hard"] == "steps"


def test_no_form_or_two_forms_go_to_the_agent():
    assert form_map.read("<p>nothing</p>")["hard"] == "none"
    two = "<form><input name=a><button>Go</button></form><form><input name=b><button>Go</button></form>"
    assert form_map.read(two)["hard"] == "several"


def test_a_field_the_browser_does_not_show_is_not_read_until_it_shows():
    page = (FORMS / "form_reveals.html").read_text()
    before = form_map.read(page)["fields"]
    after = form_map.read(page.replace(' data-sandy-hidden="1"', ""))["fields"]
    assert "other_topic" not in [f["key"] for f in before]
    assert [f["key"] for f in form_map.new_fields(before, after)] == ["other_topic"]


@pytest.mark.parametrize("said, name", [("عبّيلي النموذج، الاسم نبيل، حجم Large مع Bacon و Onion، "
                                         "الإيميل n@example.com", ""),
                                        ("fill it: name Nabeel, size large, toppings bacon and onion, "
                                         "email n@example.com", "")])
def test_his_values_go_where_the_table_says_and_choices_are_the_fields_own(said, name):
    fields = _read("httpbin.html")["fields"]
    rows = [{"field": "custname", "value": "نبيل" if "نبيل" in said else "Nabeel"},
            {"field": "custemail", "value": "n@example.com"},
            {"field": "size", "value": "Large"}, {"field": "topping", "value": "Bacon"},
            {"field": "topping", "value": "Onion"}]
    out = form_map.checked(fields, rows, _his(said))
    ops = {o["key"]: o for o in out["ops"]}
    assert out["refused"] == [] and out["missing"] == []
    assert ops["size"]["values"] == ["large"] and ops["topping"]["values"] == ["bacon", "onion"]
    assert ops["custemail"]["text"] == "n@example.com"


@pytest.mark.parametrize("language_said", ["عبّيلي النموذج، الاسم نبيل", "fill the form, name Nabeel"])
def test_a_value_he_never_gave_is_refused_and_never_typed(language_said):
    # 12 Nov's form: a telephone he never gave; 4 Nov: «123-456-7890».
    fields = _read("httpbin.html")["fields"]
    out = form_map.checked(fields, [{"field": "custtel", "value": "123-456-7890"},
                                    {"field": "custemail", "value": "nabeel@example.com"}], _his(language_said))
    assert out["ops"] == [] and {r["field"] for r in out["refused"]} == {"Telephone", "E-mail address"}


def test_a_choice_that_is_no_option_of_its_field_is_refused():
    fields = _read("httpbin.html")["fields"]
    out = form_map.checked(fields, [{"field": "size", "value": "Huge"}], _his("size huge"))
    assert out["ops"] == [] and out["refused"] == [{"field": "Pizza Size", "why": fill_values.NOT_HIS}]


def test_a_choice_named_in_the_other_script_is_his_option():
    fields = _read("httpbin.html")["fields"]
    out = form_map.checked(fields, [{"field": "size", "value": "Large"}], _his("الحجم لارج"))
    assert out["ops"] == [{"key": "size", "kind": "radio", "values": ["large"], "labels": ["Large"]}]


def test_an_arabic_forms_option_is_picked_by_its_value():
    fields = _read("form_ar.html")["fields"]
    out = form_map.checked(fields, [{"field": "fullname", "value": "نبيل السلطان"},
                                    {"field": "city", "value": "الجيزة"}, {"field": "shift", "value": "مسائي"}],
                           _his("الاسم: نبيل السلطان، المدينة الجيزة، الدوام مسائي"))
    ops = {o["key"]: o for o in out["ops"]}
    assert ops["city"]["values"] == ["giza"] and ops["shift"]["values"] == ["pm"]
    assert ops["fullname"]["text"] == "نبيل السلطان" and out["missing"] == []


@pytest.mark.parametrize("said", ["احجزلي، الاسم نبيل", "book it, name Nabeel"])
def test_required_fields_he_did_not_give_are_named_together(said):
    fields = _read("form_missing.html")["fields"]
    name = "نبيل" if "نبيل" in said else "Nabeel"
    out = form_map.checked(fields, [{"field": "name", "value": name}], _his(said))
    assert out["missing"] == ["Email", "Phone"] and [o["key"] for o in out["ops"]] == ["name"]


def test_his_profile_name_is_his_value():
    fields = _read("form_en.html")["fields"]
    out = form_map.checked(fields, [{"field": "first_name", "value": "Nabeel"}], _his("apply for me", name="Nabeel"))
    assert [o["key"] for o in out["ops"]] == ["first_name"] and out["missing"] == ["Email"]


def test_a_field_the_table_names_that_the_form_has_not_is_dropped():
    fields = _read("form_en.html")["fields"]
    out = form_map.checked(fields, [{"field": "password", "value": "x"}], _his("x"))
    assert out["ops"] == [] and out["refused"] == []


def test_the_models_table_is_read_between_its_braces():
    assert form_map.table('```json\n{"fill": [{"field": "a", "value": "b"}]}\n```') == [{"field": "a", "value": "b"}]
    assert form_map.table("no table") == []


def test_the_model_is_given_the_fields_alone_never_the_page():
    fields = _read("httpbin.html")["fields"]
    sent = form_map.asked_of_model(fields, "order", ["الاسم نبيل"])
    assert "<form" not in sent[1]["content"] and "custname" in sent[1]["content"] and "values" not in sent[1]["content"]
