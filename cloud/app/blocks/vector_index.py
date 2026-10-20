"""The Atlas vector index on sandy_entries.embedding that related-memory recall reads.

Atlas keeps it apart from Mongo's ordinary indexes, so ``create_index`` can't make it.
``ensure`` makes it when it is missing and never touches one that is there. Boot runs
it once in the background; ``python3 scripts/ensure_vector_index.py`` runs it by hand.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import Any, Optional

from pymongo.errors import PyMongoError
from pymongo.operations import SearchIndexModel

from app.blocks._base import ENTRIES
from app.utils.thread_pool import submit_background

logger = logging.getLogger(__name__)

NAME = "entries_vector"
# text-embedding-3-small vectors; the tenant and the kind go in every search's filter.
DEFINITION = {"fields": [
    {"type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine"},
    {"type": "filter", "path": "user_id"},
    {"type": "filter", "path": "kind"},
]}

# Once seen ready it stays ready for the life of the process.
_ready = False


def ensure(db: Any) -> str:
    """"present" when the index is there (left as it is), "created" when it was made.
    Raises when Atlas refuses."""
    coll = db[ENTRIES]
    if list(coll.list_search_indexes(NAME)):
        return "present"
    coll.create_search_index(SearchIndexModel(definition=DEFINITION, name=NAME, type="vectorSearch"))
    return "created"


def ensure_in_background(db: Any) -> Future:
    """``ensure`` on the shared pool, so boot never waits on Atlas; a failure is a warning."""
    def run() -> None:
        try:
            if ensure(db) == "created":
                logger.info("[vector_index] %s was missing, created it (Atlas builds it in a minute or so)", NAME)
            else:
                logger.info("[vector_index] %s is there, left as it is", NAME)
        except PyMongoError as exc:
            logger.warning("[vector_index] could not make %s: %s (related memories fall back to word search)",
                           NAME, exc)

    return submit_background(run, _label="vector_index.ensure")


def not_ready_reason(coll: Any) -> Optional[str]:
    """Why the index can't answer, or None when it can (or can't be checked).
    A missing index makes ``$vectorSearch`` return nothing, not an error, so an empty
    answer is checked here."""
    global _ready
    if _ready:
        return None
    try:
        index = coll.search_index(NAME)
    except (PyMongoError, NotImplementedError) as exc:
        logger.debug("[vector_index] could not check %s: %s", NAME, exc)
        return None
    if index is None:
        return "is missing"
    if not index.get("queryable"):
        return f"is not ready yet (status {index.get('status')})"
    _ready = True
    return None
