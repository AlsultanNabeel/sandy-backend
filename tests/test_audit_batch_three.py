"""Regressions for batch three of the 24 Aug 2026 audit."""
from __future__ import annotations

import mongomock
import pytest


OWNER = {"user_id": "o1", "chat_id": "o1", "name": "O", "is_owner": True,
         "is_guest": False, "permissions": "all", "relation": "owner"}


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


def test_the_tls_fallback_that_accepted_any_certificate_is_gone():
    """Any failure of the first connect — including an interception — used to
    retry with `tlsAllowInvalidCertificates=True`, leaving one warning behind.
    Every message, memory and voiceprint then travelled over it."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/integrations/mongodb_store.py").read_text(encoding="utf-8")
    body = src.split("def init_mongo_connection")[1]
    # Comments stripped: the deletion is explained in one, and an assertion that
    # trips over its own explanation teaches the next reader to delete the note.
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "tlsAllowInvalidCertificates" not in code
