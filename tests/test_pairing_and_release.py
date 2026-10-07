"""Pairing, one robot per account, and letting a robot go (batch 7)."""
from __future__ import annotations

import pytest
from pymongo.errors import OperationFailure

from app.features import node_store


# T11: the three indexes were built in one try, so the first failing skipped the
# uniqueness index, and two accounts pairing at the same moment could both win.

def test_one_failed_index_does_not_skip_the_others():
    built = []

    class _Coll:
        def create_index(self, keys, **kw):
            if not built and not kw.get("name"):
                built.append("failed")
                raise OperationFailure("index build failed")
            built.append(kw.get("name") or keys[0][0])

    class _Db(dict):
        def __getitem__(self, name):
            return _Coll()

    node_store.init_node_store(_Db())
    assert built == ["failed", "code_hash", "node_id_owner_unique"]
