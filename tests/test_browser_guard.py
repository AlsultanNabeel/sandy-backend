"""What stops the browser on a page whatever it was asked (`brain/browser_guard.py`): a password
field, a card field, a captcha or a payment page. Read from what the page holds (its fields,
frames and address), the same for the live browser and a page read by a plain request; each
told in his language."""
from __future__ import annotations

import pytest

from app.brain import browser_guard as G
from app.brain import lang


def _snap(fields=(), frames=(), marks=(), url="https://app.example.com/apply"):
    return {"url": url, "fields": list(fields), "frames": list(frames), "marks": list(marks)}


def test_a_plain_form_is_allowed():
    assert G.forbidden(_snap([{"type": "text", "name": "full_name", "label": "Name"},
                              {"type": "email", "name": "email"}, {"type": "tel", "name": "phone"}])) is None


def test_a_password_field_stops_it():
    assert G.forbidden(_snap([{"type": "password", "name": "pw"}])) == "password"


@pytest.mark.parametrize("field", [
    {"type": "text", "autocomplete": "cc-number"}, {"type": "text", "autocomplete": "cc-exp"},
    {"type": "text", "name": "cardNumber"}, {"type": "tel", "id": "card_number"},
    {"type": "text", "name": "cvv"}, {"type": "text", "placeholder": "CVC"},
    {"type": "text", "label": "رقم البطاقة"}, {"type": "text", "label": "Card number"}])
def test_a_card_field_stops_it(field):
    assert G.forbidden(_snap([field])) == "card"


@pytest.mark.parametrize("frame, mark", [
    ("https://www.google.com/recaptcha/api2/anchor?k=x", None),
    ("https://newassets.hcaptcha.com/captcha/v1/x", None),
    ("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x", None),
    (None, "g-recaptcha"), (None, "cf-turnstile"), (None, "h-captcha")])
def test_a_captcha_stops_it(frame, mark):
    assert G.forbidden(_snap(frames=[frame] if frame else [], marks=[mark] if mark else [])) == "captcha"


@pytest.mark.parametrize("url", ["https://shop.example.com/checkout", "https://shop.example.com/cart/checkout/",
                                 "https://shop.example.com/payment?step=2", "https://www.paypal.com/x",
                                 "https://shop.example.com/billing"])
def test_a_payment_page_stops_it(url):
    assert G.forbidden(_snap(url=url)) == "payment"


def test_a_word_inside_another_is_no_payment_page():
    assert G.forbidden(_snap(url="https://example.com/paycheck-calculator")) is None


def test_a_page_read_by_a_plain_request_is_judged_the_same():
    html = ("<form><input name='user'><input type='password' name='pass'></form>"
            "<div class='g-recaptcha'></div>")
    snap = G.of_html(html, "https://app.example.com/login")
    assert snap["fields"][1]["type"] == "password" and "g-recaptcha" in snap["marks"]
    assert G.forbidden(snap) == "password"


@pytest.mark.parametrize("why", ["password", "card", "captcha", "payment"])
@pytest.mark.parametrize("language", ["ar", "en"])
def test_each_stop_is_told_in_his_language(why, language):
    with lang.using(language):
        said = G.told(why, "app.example.com")
    assert said and "app.example.com" in said and (lang.of(said) == language)


def test_the_snapshot_script_reads_fields_frames_and_marks():
    for word in ("input", "iframe", "autocomplete", "location.href"):
        assert word in G.SNAPSHOT_JS
