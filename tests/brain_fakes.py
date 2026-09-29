"""Shared fakes for the tests/test_brain_*.py suites: a db, tenants, a scripted model."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import mongomock
import pytest

from app import db as appdb
from app.blocks import entries, init_blocks
from app.brain.model import Reply, ToolCall

A = {"chat_id": "userA", "relation": "user", "permissions": "all"}
B = {"chat_id": "userB", "relation": "user", "permissions": "all"}


@pytest.fixture
def brain_db(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    init_blocks(d)
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    # No model for time parsing in tests: words fall to the deterministic parser.
    monkeypatch.setattr("app.brain.when._chat_fn", lambda: None)
    yield d
    appdb.reset()


def call(name: str, cid: str = "c1", **args: Any) -> ToolCall:
    return ToolCall(id=cid, name=name, args=args)


class ScriptedModel:
    """Returns the scripted replies in order and records what it was sent."""

    def __init__(self, *replies: Reply):
        self.replies: List[Reply] = list(replies)
        self.seen: List[List[Dict[str, Any]]] = []

    def __call__(self, messages, tools, on_text=None) -> Optional[Reply]:
        self.seen.append([dict(m) for m in messages])
        reply = self.replies.pop(0) if self.replies else Reply(text="خلصت")
        if on_text and reply.text:
            on_text(reply.text)
        return reply


def tools_reply(*calls: ToolCall) -> Reply:
    return Reply(tool_calls=list(calls))


def text_reply(text: str) -> Reply:
    return Reply(text=text)
