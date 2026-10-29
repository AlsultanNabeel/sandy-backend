"""Azure's batch jobs (`brain/batch.py`): off unless set up, for scheduled work only, one
request a job, its answer collected once Azure has it."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from app.brain import background, batch


@pytest.fixture
def azure(monkeypatch):
    state = {"status": "in_progress", "sent": None}

    class Files:
        def create(self, file, purpose):
            state["sent"] = (json.loads(file[1]), purpose)
            return NS(id="f1")

        def content(self, fid):
            body = {"choices": [{"message": {"content": " the answer "}}]}
            return NS(text=json.dumps({"custom_id": "task", "response": {"body": body}}) + "\n")

    class Batches:
        def create(self, **kw):
            state["job"] = kw
            return NS(id="b1")

        def retrieve(self, job_id):
            return NS(status=state["status"], output_file_id="o1" if state["status"] == "completed" else None)
    monkeypatch.setattr(batch, "_azure", lambda: NS(files=Files(), batches=Batches()))
    monkeypatch.setenv("SANDY_BATCH_DEPLOYMENT", "sandy-batch")
    return state


def test_off_unless_a_batch_deployment_is_set(monkeypatch):
    monkeypatch.delenv("SANDY_BATCH_DEPLOYMENT", raising=False)
    assert batch.enabled(background.SCHEDULED) is False


def test_only_scheduled_work_may_go(azure):
    assert batch.enabled(background.SCHEDULED) is True
    assert batch.enabled(background.DIRECT) is False and batch.enabled(background.BACKGROUND) is False


def test_one_request_is_submitted_and_collected_once_done(azure):
    job = batch.submit("task", [{"role": "user", "content": "x"}], max_tokens=10, temperature=0)
    line, purpose = azure["sent"]
    assert job == "b1" and purpose == "batch" and line["body"]["model"] == "sandy-batch"
    assert azure["job"]["completion_window"] == "24h"
    assert batch.collect(job) is None
    azure["status"] = "completed"
    assert batch.collect(job) == "the answer"


def test_a_failed_job_raises(azure):
    azure["status"] = "failed"
    with pytest.raises(RuntimeError):
        batch.collect("b1")
