"""The eval script's own logic (`scripts/eval_brain.py`), without a model: the args a step
expects, repeats that disagree, the saved result and its baseline, and what a run cost."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import mongomock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_brain as E  # noqa: E402


def test_importing_it_reads_no_env_file_and_no_command_line():
    assert E.ARGS.repeat == 1 and E.ARGS.save is False and E.ARGS.model is None


def test_args_match_whole_values_and_words_inside_text():
    calls = [("list_add", {"list": "shopping", "text": "حليب وخبز"}),
             ("schedule", {"kind": "reminder", "text": "اتصل بأمي", "in_minutes": 60})]
    assert E._args_check({"list_add": {"list": "shopping", "text": "خبز"}}, calls) == []
    assert E._args_check({"schedule": {"in_minutes": 60}}, calls) == []
    bad = E._args_check({"list_add": {"list": "tasks"}}, calls)
    assert len(bad) == 1 and "list_add" in bad[0]
    assert E._args_check({"weather": {"city": "عمان"}}, calls)


def test_one_matching_call_is_enough():
    calls = [("list_add", {"list": "tasks", "text": "x"}), ("list_add", {"list": "shopping", "text": "بيض"})]
    assert E._args_check({"list_add": {"list": "shopping"}}, calls) == []


def test_a_case_that_passed_and_failed_across_repeats_is_named():
    runs = {"a": [True, True], "b": [True, False], "c": [False, False]}
    assert E._disagreeing(runs) == ["b"]


def test_compare_names_what_moved_against_the_baseline():
    base = {"cases": {"a": True, "b": True, "c": False}}
    now = {"cases": {"a": True, "b": False, "c": True, "d": True}}
    moved = E._compare(base, now)
    assert moved == {"fell": ["b"], "rose": ["c"], "new": ["d"]}
    assert E._differences(moved) == 2


def test_the_first_save_becomes_the_baseline_and_the_next_does_not(tmp_path):
    first = {"when": "2026-10-28T10:00", "cases": {"a": True}, "passed": 1, "total": 1}
    path, base = E._save(first, tmp_path)
    assert path.exists() and base is None
    assert json.loads((tmp_path / "baseline.json").read_text())["cases"] == {"a": True}
    second = {"when": "2026-10-28T11:00", "cases": {"a": False}, "passed": 0, "total": 1}
    path2, base2 = E._save(second, tmp_path)
    assert path2 != path and base2["cases"] == {"a": True}
    assert json.loads((tmp_path / "baseline.json").read_text())["cases"] == {"a": True}


@pytest.fixture
def db():
    from app import db as appdb
    d = mongomock.MongoClient().db
    appdb.configure(d)
    yield d
    appdb.reset()


def test_what_a_case_cost_comes_from_its_traces(db):
    from app.features import trace_store
    for tokens_in in (1000, 500):
        t = trace_store.Trace("eval", "chat")
        t.add_model_call("azure", "gpt-4.1", tokens_in=tokens_in, tokens_out=100)
        t.finish(request="x", reply="y")
    spent = E._spent()
    assert spent["tokens_in"] == 1500 and spent["tokens_out"] == 200
    assert spent["usd"] == pytest.approx(1500 * 2.0 / 1e6 + 200 * 8.0 / 1e6)


def test_a_case_the_model_could_not_answer_is_tried_again_then_set_apart(monkeypatch):
    """A 429 or an outage is no outcome: the case waits and runs again, and one that still
    gets no answer is counted apart, never as a fail."""
    outcomes = iter([{"error": True}, {"error": True}, {"error": False, "failures": []}])
    waits = []
    monkeypatch.setattr(E, "_run_case", lambda case: {"name": "a", "seconds": 1.0, "tokens_in": 0,
                                                     "tokens_out": 0, "usd": 0.0, "failures": [],
                                                     **next(outcomes)})
    monkeypatch.setattr(E.time, "sleep", waits.append)
    r = E._run_answered({"name": "a"})
    assert r["error"] is False and len(waits) == 2

    monkeypatch.setattr(E, "_run_case", lambda case: {"name": "a", "seconds": 1.0, "tokens_in": 0,
                                                     "tokens_out": 0, "usd": 0.0,
                                                     "failures": ["x"], "error": True})
    assert E._run_answered({"name": "a"})["error"] is True


def test_cases_with_no_answer_are_left_out_of_the_comparison():
    base = {"cases": {"a": True, "b": True}}
    now = {"cases": {"a": True, "b": None}}
    assert E._compare(base, now) == {"fell": [], "rose": [], "new": []}


def test_every_arabic_case_has_an_english_sister_with_the_same_checks():
    from eval_cases import CASES
    by_name = {c["name"]: c for c in CASES}
    arabic = [c for c in CASES if c.get("lang", "ar") == "ar"]
    assert arabic
    for c in arabic:
        sister = by_name.get(f"{c['name']} · en")
        assert sister, f"no English sister for {c['name']}"
        assert sister["lang"] == "en"
        assert len(sister["steps"]) == len(c["steps"])
        for a, e in zip(c["steps"], sister["steps"]):
            checks = set(a) - {"say", "english"}
            assert checks <= set(e), f"{c['name']}: the English sister drops {checks - set(e)}"
            assert e.get("english"), f"{sister['name']}: the reply must be checked to be English"


def test_the_score_is_given_per_language_and_english_may_not_trail_by_more_than_five():
    langs = {"a": "ar", "b": "ar", "a · en": "en", "b · en": "en"}
    outcome = {"a": True, "b": True, "a · en": True, "b · en": False}
    scores = E._by_language(outcome, langs)
    assert scores == {"ar": (2, 2), "en": (1, 2)}
    assert E._language_gap_ok(scores) is False
    assert E._language_gap_ok({"ar": (19, 20), "en": (18, 20)}) is True
    assert E._language_gap_ok({"ar": (18, 20), "en": (20, 20)}) is True


def test_a_row_is_found_whatever_its_case():
    assert E._has([{"text": "Water the plants"}], "water")


def test_an_english_reply_has_no_arabic_word_but_names_may_stay():
    assert E._is_english("Added milk ✅")
    assert not E._is_english("I added milk, يا عيوني!")
    assert E._is_english("Turned on «ضو الصالون» ✨")
    assert E._is_english("Turned on ضو الصالون ✨")


def test_the_stand_ins_answer_in_the_turns_language():
    from app.brain import lang
    with lang.using("en"):
        assert E._STAND_INS["device_control"]({"device": "living_light", "action": "off"}, None)["reply"] \
            == "Turned off living_light"
        assert "ا" not in E._STAND_INS["image"]({}, None)["reply"]
    with lang.using("ar"):
        assert E._STAND_INS["image"]({}, None)["reply"] == lang.PHRASES["image_done"]["ar"]


def test_two_runs_are_stable_while_at_most_five_percent_of_the_cases_moved():
    # The share, not a count: 4 of 83 is 4.8%, 5 of 83 is 6%; Arabic and English alike.
    assert E._stable(4, 83) is True and E._stable(5, 83) is False
    assert E._stable(2, 41) is True and E._stable(3, 41) is False
    assert E._stable(0, 0) is True


def test_a_run_may_set_the_models_temperature():
    assert E._args(["--temperature", "0.2"]).temperature == 0.2
    assert E._args([]).temperature is None


def test_a_run_fails_only_on_the_plans_conditions():
    # Each language ninety percent or more, at most five percent of the cases moved, English
    # at most five points behind Arabic; a case that fell on its own is a warning.
    ok, warnings = E._verdict({"ar": (41, 41), "en": (41, 42)}, moved=1, total=83,
                              failed=["apply a scene · en"])
    assert ok is True and any("apply a scene · en" in w for w in warnings)
    assert E._verdict({"ar": (36, 41), "en": (39, 42)}, 0, 83, [])[0] is False   # ar 87.8%
    assert E._verdict({"ar": (41, 41), "en": (37, 42)}, 0, 83, [])[0] is False   # en 88%
    assert E._verdict({"ar": (41, 41), "en": (39, 42)}, 0, 83, [])[0] is False   # 7 points apart
    assert E._verdict({"ar": (41, 41), "en": (41, 42)}, 5, 83, [])[0] is False   # 6% moved
    assert E._verdict({"ar": (40, 41), "en": (40, 42)}, 4, 83, [])[0] is True


def test_cases_with_no_answer_are_a_warning_not_a_failure():
    ok, warnings = E._verdict({"ar": (40, 40), "en": (41, 41)}, 0, 83, [], unanswered=["x"])
    assert ok is True and any("x" in w for w in warnings)


def test_a_run_may_take_the_responses_api_and_an_effort():
    a = E._args(["--model", "gpt-6-luna", "--api", "responses", "--reasoning", "medium"])
    assert (a.api, a.reasoning) == ("responses", "medium")
    assert (E._args([]).api, E._args([]).reasoning) == ("chat", "low")


def test_a_runs_spend_counts_the_reasoning_tokens(monkeypatch):
    from app import db as appdb
    from app.features import trace_store
    d = mongomock.MongoClient().db
    d[trace_store.COLLECTION].insert_many([
        {"tokens_in": 10, "tokens_out": 5, "tokens_reasoning": 3, "cost_usd": 0.1},
        {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.1}])
    appdb.configure(d)
    try:
        assert E._spent()["tokens_reasoning"] == 3
    finally:
        appdb.reset()
