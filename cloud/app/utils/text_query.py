"""Case-insensitive text matching, done in the database instead of in Python.

Several stores used to answer "which habit is called roughly this?" by reading
every document in the collection and comparing strings in a Python loop. That is
wrong twice over.

It sends the whole collection across the network to find one row, so the cost
grows with everything the user has ever saved — a person with five thousand
shopping items pulled five thousand documents to tick one off. And it has no
ceiling, so a single request could load an entire account into memory.

`re.escape` is not a detail. The user's own text goes into a regular expression,
so without escaping, an item named `.*` matches everything, `^` matches nothing,
and a pattern like `(a+)+$` can hang the matcher on a long string — a denial of
service written by a user who was only naming a habit.

These return query fragments rather than running queries, so a caller can merge
them with its own filters:

    coll.find_one({"archived": {"$ne": True}, **contains("name", text)})
"""

from __future__ import annotations

import re
from typing import Any, Dict


def contains(field: str, text: str) -> Dict[str, Any]:
    """Documents whose `field` contains `text`, ignoring case."""
    return {field: {"$regex": re.escape(str(text or "").strip()), "$options": "i"}}


def equals(field: str, text: str) -> Dict[str, Any]:
    """Documents whose `field` equals `text` exactly, ignoring case.

    Anchored at both ends, which is why it is not the same as `contains` with a
    short string: "The Hobbit" must not be found by searching for "hobbit" when
    the caller asked for an exact title.
    """
    return {field: {"$regex": f"^{re.escape(str(text or '').strip())}$", "$options": "i"}}
