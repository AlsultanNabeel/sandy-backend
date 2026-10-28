"""The turn trace: one row per turn of chat, voice or background work, kept thirty days.

What a turn was asked, what it answered, every tool it ran (arguments, result, time) and
every model call (tokens, time, cost). The words — the request, the reply, tools'
arguments and results — are sealed with the memory key (`ltm_crypto`); without the key
none are kept, only the numbers, never plain text.

A turn collects into a `Trace` that is current for its thread (`using`, a context
variable, so the side-by-side tools of one step see it); the model client and the tools
report into whatever is current (`note_model_call`, `note_tool`) and do nothing when
nothing is. `finish` writes the row and never raises: a trace never breaks a turn.

Rows are written under their user (`ScopedCollection`). Only the owner reads them
(`api/owner_api.py`), across users, and the words open for the owner's own turns only.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

from pymongo.errors import PyMongoError

from app.blocks._base import new_id
from app.db import get_db
from app.features import pricing
from app.utils import ltm_crypto
from app.utils.tenant_db import ScopedCollection

logger = logging.getLogger(__name__)

COLLECTION = "sandy_traces"
KEEP_DAYS = 30
SOURCES = ("chat", "voice", "background")

_current: ContextVar[Optional["Trace"]] = ContextVar("sandy_trace", default=None)


def init_trace_store(mongo_db) -> None:
    if mongo_db is None:
        return
    for keys, extra in (([("expire_at", 1)], {"expireAfterSeconds": 0}),
                        ([("user_id", 1), ("at", -1)], {}),
                        ([("at", -1)], {})):
        try:
            mongo_db[COLLECTION].create_index(keys, background=True, **extra)
        except PyMongoError as exc:  # one index never stops the boot
            logger.warning("[traces] index %s skipped: %s", keys, exc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seal(value: Any) -> Optional[str]:
    """The value sealed with the memory key, or None: never plain text."""
    if value is None or not ltm_crypto.encryption_ready():
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    sealed = ltm_crypto.encrypt_field(text)
    return sealed if sealed.startswith(ltm_crypto._PREFIX) else None


def _open(value: Optional[str], as_json: bool) -> Any:
    if not value:
        return None
    text = ltm_crypto.decrypt_field(value)
    if text.startswith(ltm_crypto._PREFIX):
        return None
    if not as_json:
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


def _collection(user_id: str):
    return ScopedCollection(get_db()[COLLECTION], user_id, bump=False)


class Trace:
    """What one turn did, gathered while it runs."""

    def __init__(self, user_id: str, source: str, *, thread_id: str = "",
                 turn_id: Optional[str] = None):
        self.id = turn_id or new_id()
        self.user_id = str(user_id or "")
        self.source = source if source in SOURCES else "chat"
        self.thread_id = str(thread_id or "")
        self.at = _now()
        self._t0 = time.perf_counter()
        self._lock = threading.Lock()
        self.model_calls: List[Dict[str, Any]] = []
        self.tools: List[Dict[str, Any]] = []

    def add_model_call(self, provider: str, model: str, *, tokens_in: int = 0,
                       tokens_out: int = 0, tokens_cached: int = 0, ms: float = 0) -> None:
        call = {"provider": provider, "model": str(model or ""), "tokens_in": int(tokens_in or 0),
                "tokens_out": int(tokens_out or 0), "tokens_cached": int(tokens_cached or 0),
                "ms": round(float(ms or 0))}
        with self._lock:
            self.model_calls.append(call)

    def add_tool(self, name: str, args: Any, result: Any, ms: float = 0) -> None:
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        with self._lock:
            self.tools.append({"name": name, "args": args, "result": result, "ok": ok,
                               "ms": round(float(ms or 0))})

    def _row(self, request: str, reply: str, routed_by: str, error: Optional[str]) -> Dict[str, Any]:
        with self._lock:
            calls = list(self.model_calls)
            used = list(self.tools)
        cost = sum(pricing.cost(c["model"], tokens_in=c["tokens_in"], tokens_out=c["tokens_out"],
                                tokens_cached=c["tokens_cached"]) for c in calls)
        return {
            "_id": self.id, "at": self.at, "source": self.source, "thread_id": self.thread_id,
            "routed_by": routed_by,
            "request": _seal(request or None), "reply": _seal(reply or None),
            "tools": [{**t, "args": _seal(t["args"]), "result": _seal(t["result"])} for t in used],
            "model_calls": calls,
            "tokens_in": sum(c["tokens_in"] for c in calls),
            "tokens_out": sum(c["tokens_out"] for c in calls),
            "cost_usd": round(cost, 8),
            "ms_total": round((time.perf_counter() - self._t0) * 1000),
            "skills": [], "task_id": None, "error": error,
            "encrypted": ltm_crypto.encryption_ready(),
            "expire_at": self.at + timedelta(days=KEEP_DAYS),
        }

    def finish(self, *, request: str = "", reply: str = "", routed_by: str = "",
               error: Optional[str] = None) -> Optional[str]:
        """Write the row; its id, or None when it could not be written (logged, not raised)."""
        if not self.user_id:
            logger.warning("[traces] %s turn %s has no user — not kept", self.source, self.id)
            return None
        if get_db() is None:
            return None
        try:
            _collection(self.user_id).insert_one(self._row(request, reply, routed_by, error))
            return self.id
        except Exception as exc:  # noqa: BLE001 — a trace never breaks the turn
            logger.warning("[traces] %s turn %s not kept: %s", self.source, self.id, exc)
            return None


@contextmanager
def using(trace: Optional[Trace]) -> Iterator[Optional[Trace]]:
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


def current() -> Optional[Trace]:
    return _current.get()


def note_model_call(provider: str, model: str, *, tokens_in: int = 0, tokens_out: int = 0,
                    tokens_cached: int = 0, ms: float = 0) -> None:
    trace = _current.get()
    if trace is not None:
        trace.add_model_call(provider, model, tokens_in=tokens_in, tokens_out=tokens_out,
                             tokens_cached=tokens_cached, ms=ms)


def note_usage(provider: str, model: str, usage: Any, ms: float = 0) -> None:
    """An OpenAI-shaped ``usage`` (prompt / completion / cached tokens) into the current trace."""
    if usage is None:
        return
    details = getattr(usage, "prompt_tokens_details", None)
    note_model_call(provider, model, tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                    tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                    tokens_cached=getattr(details, "cached_tokens", 0) or 0, ms=ms)


def note_live_usage(trace: Optional[Trace], model: str, usage: Any) -> None:
    """A live voice message's ``usage_metadata`` into the call's turn."""
    if trace is None or usage is None:
        return
    trace.add_model_call("gemini", model, tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
                         tokens_out=getattr(usage, "response_token_count", 0) or 0,
                         tokens_cached=getattr(usage, "cached_content_token_count", 0) or 0)


def note_tool(name: str, args: Any, result: Any, ms: float = 0) -> None:
    trace = _current.get()
    if trace is not None:
        trace.add_tool(name, args, result, ms)


@contextmanager
def background(user_id: str, what: str) -> Iterator[Trace]:
    """Model calls made for a user outside a turn (a summary, a title): a row of numbers,
    written only when a model call was made."""
    trace = Trace(user_id, "background")
    with using(trace):
        yield trace
    if trace.model_calls:
        trace.finish(routed_by=what)


# ── the owner's reads, across users ──────────────────────────────────────────

def _raw():
    return get_db()[COLLECTION]


def _without_words(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("request", "reply", "expire_at")}
    out["tools"] = [{k: v for k, v in t.items() if k not in ("args", "result")}
                    for t in row.get("tools") or []]
    return out


def list_traces(owner_id: str, *, limit: int = 50, user: Optional[str] = None,
                source: Optional[str] = None) -> List[Dict[str, Any]]:
    """The newest turns, numbers and names only, for the owner."""
    query: Dict[str, Any] = {}
    if user:
        query["user_id"] = str(user)
    if source:
        query["source"] = str(source)
    rows = _raw().find(query).sort("at", -1).limit(max(1, min(int(limit), 200)))
    return [_without_words(r) for r in rows]


def get_trace(owner_id: str, trace_id: str) -> Optional[Dict[str, Any]]:
    """One turn whole; its words opened only when it is the owner's own."""
    row = _raw().find_one({"_id": str(trace_id)})
    if row is None:
        return None
    own = bool(owner_id) and row.get("user_id") == owner_id
    out = {k: v for k, v in row.items() if k != "expire_at"}
    out["request"] = _open(row.get("request"), False) if own else None
    out["reply"] = _open(row.get("reply"), False) if own else None
    out["tools"] = [{**t, "args": _open(t.get("args"), True) if own else None,
                     "result": _open(t.get("result"), True) if own else None}
                    for t in row.get("tools") or []]
    return out


def _label(user_id: str) -> str:
    from app.features import users_store

    user = users_store.get_user(user_id) or {}
    return str(user.get("name") or user.get("email") or "")


def costs(days: int = 30) -> Dict[str, Any]:
    """What was spent in the last ``days``, by user and by source."""
    match = {"$match": {"at": {"$gte": _now() - timedelta(days=days)}}}
    users = [{"user_id": str(g["_id"] or ""), "label": _label(str(g["_id"] or "")),
              "turns": g["turns"], "tokens_in": g["tokens_in"], "tokens_out": g["tokens_out"],
              "usd": round(g["usd"], 6)}
             for g in _raw().aggregate([match, {"$group": {
                 "_id": "$user_id", "turns": {"$sum": 1}, "tokens_in": {"$sum": "$tokens_in"},
                 "tokens_out": {"$sum": "$tokens_out"}, "usd": {"$sum": "$cost_usd"}}}])]
    sources = [{"source": str(g["_id"] or ""), "turns": g["turns"], "usd": round(g["usd"], 6)}
               for g in _raw().aggregate([match, {"$group": {
                   "_id": "$source", "turns": {"$sum": 1}, "usd": {"$sum": "$cost_usd"}}}])]
    return {"days": days, "total_usd": round(sum(u["usd"] for u in users), 6),
            "by_user": sorted(users, key=lambda u: -u["usd"]),
            "by_source": sorted(sources, key=lambda s: -s["usd"]), "by_task": []}
