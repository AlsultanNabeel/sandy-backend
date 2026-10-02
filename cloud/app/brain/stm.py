"""Short-term memory: the last turns of every thread, on every channel (`sandy_stm`).

One doc per thread: ``{key: "<thread>:<user>", user_id, history: [...], updated_at}``.
Chat, the robot's voice and the in-app call all write here with ``via``, and
`recent_turns_for_user` reads a person's last turns across all of them, so a line
said aloud reaches the next chat turn.

On Mongo rather than Redis on purpose: the free Redis tier hit its monthly request
cap and memory silently froze.

A conversation is summarised once, into one ``summary`` log entry (`blocks.entries`),
in the background: when the next message comes after a pause of ``SESSION_GAP``, or
when a long one fills the thread and its older half is let go. Summarised turns are
marked ``summarized`` so no turn is summarised twice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.errors import PyMongoError

from app.utils.thread_pool import submit_background

logger = logging.getLogger(__name__)

STM_TTL = 60 * 60 * 24 * 30  # drives the Mongo TTL index on STM docs
MAX_STM_MESSAGES = 40
# A long thread drops to this many when it fills, so it is summarised in one go.
KEEP_AFTER_TRIM = 20
# A pause this long ends a conversation; the next message starts a new one.
SESSION_GAP = timedelta(minutes=30)
_STM_COLL = "sandy_stm"
_stm_index_ready = False

_SUMMARY_PROMPT = "لخّص المحادثة التالية في جملتين أو ثلاث بالعربي. ركّز على القرارات والمعلومات المهمة فقط."


def _ensure_stm_indexes(coll) -> bool:
    """Each index on its own: one failing must not skip the rest. True when all exist.

    ``(user_id, updated_at)`` is what keeps `recent_turns_for_user` — every chat
    turn and every voice session — from scanning every conversation on the server.
    """
    jobs = (
        ("key", lambda: coll.create_index("key", unique=True, background=True)),
        ("updated_at_ttl", lambda: coll.create_index(
            "updated_at", expireAfterSeconds=STM_TTL, background=True)),
        ("user_id+updated_at", lambda: coll.create_index(
            [("user_id", 1), ("updated_at", -1)], background=True)),
    )
    ok = True
    for label, job in jobs:
        try:
            job()
        except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
            ok = False
            logger.warning("[stm] index %s failed: %s", label, exc)
    return ok


def _stm_collection():
    """The STM collection, or None before Mongo is wired. Index creation retries
    until it succeeds: a missing index breaks nothing, it only gets slower forever."""
    global _stm_index_ready
    from app.db import get_db

    mongo_db = get_db()
    if mongo_db is None:
        return None
    coll = mongo_db[_STM_COLL]
    if not _stm_index_ready:
        _stm_index_ready = _ensure_stm_indexes(coll)
    return coll


def load(thread_id: str, user_id: str) -> List[Dict[str, Any]]:
    coll = _stm_collection()
    if coll is None:
        return []
    try:
        doc = coll.find_one({"key": f"{thread_id}:{user_id}"}, {"_id": 0, "history": 1})
        return (doc or {}).get("history", []) or []
    except Exception as exc:  # noqa: BLE001 — memory is never worth a failed reply
        logger.warning("[stm] load failed: %s", exc)
        return []


def recent_turns_for_user(user_id: str, limit: int = 6, *,
                          threads_out: Optional[Dict[str, List[Dict[str, Any]]]] = None
                          ) -> List[Dict[str, Any]]:
    """This person's last turns on any channel, ordered by their own timestamps.

    ``threads_out`` is filled with ``{key: history}`` for every thread doc read, so
    the chat turn can skip reading its own thread a second time.
    """
    coll = _stm_collection()
    if coll is None or not user_id:
        return []
    try:
        docs = coll.find({"user_id": str(user_id)},
                         {"_id": 0, "key": 1, "history": 1, "updated_at": 1}
                         ).sort("updated_at", -1).limit(5)
        turns: List[Dict[str, Any]] = []
        for d in docs:
            turns.extend(d.get("history") or [])
            if threads_out is not None and d.get("key"):
                threads_out[d["key"]] = list(d.get("history") or [])
        turns.sort(key=lambda m: str(m.get("timestamp") or ""))
        return turns[-limit:]
    except Exception as exc:  # noqa: BLE001 — memory is never worth a failed reply
        logger.warning("[stm] cross-channel read failed: %s", exc)
        return []


def history(thread_id: str, user_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(this thread's turns, what the prompt sees): the other channels' recent
    turns go before the thread's own, without repeating a line."""
    threads: Dict[str, List[Dict[str, Any]]] = {}
    cross = recent_turns_for_user(user_id, limit=6, threads_out=threads)
    key = f"{thread_id}:{user_id}"
    own = threads[key] if key in threads else load(thread_id, user_id)
    seen = {(m.get("role"), m.get("content")) for m in own}
    extra = [m for m in cross if (m.get("role"), m.get("content")) not in seen]
    return own, extra + own


def _summarize(thread_id: str, user_id: str, messages: List[Dict[str, Any]],
               source: str) -> None:
    """The overflowing turns as one ``summary`` entry (runs on the background pool)."""
    from app.blocks import entries
    from app.integrations.openai_client import chat_fn
    from app.utils.user_profiles import resolve_display_name

    user_label = resolve_display_name(user_id, default="المستخدم")
    turns = "\n".join(f"{user_label if m['role'] == 'user' else 'Sandy'}: {m['content']}"
                      for m in messages if m.get("content"))
    try:
        resp = chat_fn()(messages=[{"role": "system", "content": _SUMMARY_PROMPT},
                                   {"role": "user", "content": turns}], max_tokens=200)
        summary = (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — provider boundary; a lost summary costs no reply
        logger.warning("[stm] summary failed: %s", exc)
        return
    if summary:
        entries.add("summary", summary, {"thread_id": str(thread_id),
                                         "source_turns": len(messages)}, source=source)


def _ended(turns: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    """The last conversation's unsummarised turns when it ended (a pause of
    ``SESSION_GAP`` before this message), else nothing. Same dicts, to be marked."""
    if not turns:
        return []
    try:
        last = datetime.fromisoformat(str(turns[-1].get("timestamp") or ""))
    except ValueError:
        return []
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if now - last < SESSION_GAP:
        return []
    return [m for m in turns if not m.get("summarized")]


def rewind(thread_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Forget the thread's last exchange (its last user line and any reply after it),
    so the same line, or an edited one, can be answered again in its place. Returns
    what that reply did to the blocks (its `effects`), for the caller to take back."""
    coll = _stm_collection()
    if coll is None:
        return []
    key = f"{thread_id}:{user_id}"
    effects: List[Dict[str, Any]] = []
    try:
        doc = coll.find_one({"key": key}, {"_id": 0, "history": 1})
        turns = list((doc or {}).get("history") or [])
        while turns and turns[-1].get("role") == "assistant":
            effects = list(turns.pop().get("effects") or []) + effects
        if turns and turns[-1].get("role") == "user":
            turns.pop()
        coll.update_one({"key": key}, {"$set": {"history": turns}})
    except PyMongoError as exc:  # memory is never worth a failed reply
        logger.warning("[stm] rewind failed: %s", exc)
    return effects


def take_last_effects(thread_id: str, user_id: str) -> List[Dict[str, Any]]:
    """What the thread's last reply did to the blocks, handed over once: the reply keeps
    its words, but its effects are cleared so they cannot be taken back twice."""
    coll = _stm_collection()
    if coll is None:
        return []
    key = f"{thread_id}:{user_id}"
    try:
        doc = coll.find_one({"key": key}, {"_id": 0, "history": 1})
        turns = list((doc or {}).get("history") or [])
        for i in range(len(turns) - 1, -1, -1):
            if turns[i].get("role") != "assistant":
                continue
            effects = list(turns[i].get("effects") or [])
            if effects:
                turns[i] = {k: v for k, v in turns[i].items() if k != "effects"}
                coll.update_one({"key": key}, {"$set": {"history": turns}})
            return effects
    except PyMongoError as exc:  # memory is never worth a failed reply
        logger.warning("[stm] take effects failed: %s", exc)
    return []


def cut_last(thread_id: str, user_id: str, text: str) -> None:
    """The last reply, as the user saw it before stopping it (the turn was already over)."""
    coll = _stm_collection()
    if coll is None:
        return
    key = f"{thread_id}:{user_id}"
    try:
        doc = coll.find_one({"key": key}, {"_id": 0, "history": 1})
        turns = list((doc or {}).get("history") or [])
        if turns and turns[-1].get("role") == "assistant":
            turns[-1] = {**turns[-1], "content": text}
            coll.update_one({"key": key}, {"$set": {"history": turns}})
    except PyMongoError as exc:  # memory is never worth a failed reply
        logger.warning("[stm] cut failed: %s", exc)


def save(thread_id: str, user_id: str, user_msg: str, reply: str, *,
         prior_history: Optional[List[Dict[str, Any]]] = None, via: str = "",
         source: str = "chat", effects: Optional[List[Dict[str, Any]]] = None) -> None:
    """Append the turn; ``prior_history`` (this thread's turns, already read this turn)
    saves a second read. Runs in the caller's tenant: the overflow summary is scoped."""
    coll = _stm_collection()
    if coll is None:
        return
    try:
        key = f"{thread_id}:{user_id}"
        now = datetime.now(timezone.utc)
        ts = now.isoformat()
        if prior_history is not None:
            turns = list(prior_history)
        else:
            doc = coll.find_one({"key": key}, {"_id": 0, "history": 1})
            turns = (doc or {}).get("history", []) or []
        to_summarize = _ended(turns, now)
        # `via` is where it was said, so «when did I tell you that?» has an answer.
        turns.append({"role": "user", "content": user_msg, "timestamp": ts, "via": via})
        if reply:
            # What the reply did to the blocks, so a regenerate or an edit can take it back.
            turns.append({"role": "assistant", "content": reply, "timestamp": ts, "via": via,
                          **({"effects": effects} if effects else {})})
        if len(turns) > MAX_STM_MESSAGES:
            dropped, turns = turns[:-KEEP_AFTER_TRIM], turns[-KEEP_AFTER_TRIM:]
            to_summarize += [m for m in dropped if not m.get("summarized") and m not in to_summarize]
        if to_summarize:
            for m in to_summarize:
                m["summarized"] = True
            submit_background(_summarize, thread_id, user_id, to_summarize,
                              source, _label="stm_summarize")
        coll.update_one({"key": key}, {"$set": {"history": turns,
                                                "updated_at": now, "user_id": str(user_id)}},
                        upsert=True)
    except Exception as exc:  # noqa: BLE001 — memory is never worth a failed reply
        logger.warning("[stm] save failed: %s", exc)
