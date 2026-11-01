"""The task email reads right in Arabic (owner, 1 Nov 2026): «ليمون» showed as «ليمون» turned
around, and «orange» among Arabic words pulled the line apart. Every name is isolated (`<bdi>`
in the HTML, the isolate marks in the plain copy) and every line has its direction; the time
reads as people say it («٣١ تشرين الأول، ٦:٤٥ المسا», «31 Oct, 6:45 PM»); «0 لسا و21 تم» is
«٢١ تم، وما في شي لسا»; and several rows with the same change are one line. In both
languages, with Arabic and English names mixed."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.brain import lang, task_diff
from app.notify import mail
from app.utils.user_profiles import active_user_profile_context

FSI, PDI = "⁨", "⁩"
AT = datetime(2026, 10, 31, 16, 45, tzinfo=timezone.utc)           # 6:45 PM in Cairo


def _rows(language, body, state=""):
    return [{"task_id": "t1", "title": "التسوق", "body": body, "state": state, "at": AT, "lang": language}]


@pytest.mark.parametrize("language", ["ar", "en"])
def test_every_name_is_isolated_and_every_line_has_its_direction(brain_db, language):  # noqa: F811
    with active_user_profile_context(A), lang.using(language):
        _, plain, page = mail._compose(_rows(language, "«ليمون» صار تم\n«orange» صار تم"))
    side = "rtl" if language == "ar" else "ltr"
    assert "«<bdi>ليمون</bdi>»" in page and "«<bdi>orange</bdi>»" in page
    assert f'<div dir="{side}">«<bdi>orange</bdi>» صار تم</div>' in page
    assert f"«{FSI}orange{PDI}»" in plain and f"«{FSI}ليمون{PDI}»" in plain


@pytest.mark.parametrize("language, said", [("ar", "٣١ تشرين الأول، ٦:٤٥ المسا"),
                                            ("en", "31 Oct, 6:45 PM")])
def test_the_time_reads_as_people_say_it(brain_db, language, said):  # noqa: F811
    with active_user_profile_context(A), lang.using(language):
        _, plain, page = mail._compose(_rows(language, "x"))
    assert said in plain and said in page


@pytest.mark.parametrize("language, said", [("ar", "٢١ تم، وما في شي لسا"), ("en", "21 done, nothing open")])
def test_a_list_all_done_says_so_plainly(language, said):
    rows = [{"id": str(n), "text": f"t{n}", "done": True} for n in range(21)]
    with lang.using(language):
        assert task_diff.describe({"rows": rows}) == said


def _done(*names):
    return {"added": [], "removed": [], "numbers": [], "paragraphs_added": [], "paragraphs_removed": [],
            "changed": [{"before": {"id": n, "list": "shopping", "text": n, "done": False},
                         "after": {"id": n, "list": "shopping", "text": n, "done": True},
                         "fields": ["done"]} for n in names]}


@pytest.mark.parametrize("language, said", [
    ("ar", "صاروا ٧ عناصر تم: «ليمون»، «orange»، «خبز»، «milk»، «رز»، وغيرهم"),
    ("en", "7 items are done: «ليمون», «orange», «خبز», «milk», «رز», and more"),
])
def test_rows_with_the_same_change_are_one_line(language, said):
    with lang.using(language):
        assert task_diff.template(_done("ليمون", "orange", "خبز", "milk", "رز", "تفاح", "lemon")) == said


@pytest.mark.parametrize("language, said", [("ar", "«orange» صار تم"), ("en", "«orange» is done")])
def test_one_row_is_its_own_line(language, said):
    with lang.using(language):
        assert task_diff.template(_done("orange")) == said
