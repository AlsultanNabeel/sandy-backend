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
