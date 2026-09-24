"""The fast path: answer a bare device command without asking a model.

WHY
---
A chat turn costs two model calls in series — the function-calling router picks
the tool, then the reply is written (ARCHITECTURE_MAP §12.5). For «شغّل الضو»
both of them are spent on a sentence with one possible reading, and the user is
standing in a dark room while a round trip to Azure decides that "turn the light
on" means turning the light on.

This module answers that class of sentence with no model call at all. It does
**not** execute anything: it returns the same `function_call` the router would
have produced, and `execute_node` → `ToolDispatcher` → `device_control` →
`command_payload` → `tenant_owns_topic` run exactly as before. Every tenancy and
actuation check downstream is untouched, which is the property that makes this
safe to add — the fast path can be wrong about *intent* and still cannot be
wrong about *permission*.

THE RULE IT OBEYS, AND WHY IT IS NOT WHAT C8 BANS
-------------------------------------------------
CONVENTIONS.md C8 bans inferring intent from substring matching on free text,
because "keyword matching fires on words that appear inside stories, quotes, or
negations". That rule is right, and this module is built to satisfy it rather
than to carve an exception out of it:

* **The candidates are structured data, not a keyword list.** C8 allows keywords
  to "rank or tie-break already-structured data". The phrases matched here are
  generated at match time from the caller's own `sandy_devices` rows — their
  labels, their control types — and the action is chosen by `command_payload`,
  which C8's own neighbourhood calls the only validator. A phrase this module
  can match does not exist until a user registers the device it names.

* **It matches the whole utterance, never a part of it.** After a verb and a
  device label are removed, *nothing may be left*. This is the difference that
  matters for the case C8 describes, and it is worth being concrete about:

      "شغّل الضو"                          → matches: verb + device, nothing left.
      "كان أخوي بحكي معي وطولنا بالحكي      → no match. After "شغل" and "الضو"
       فاجا أخوي الصغير وحكتلو شغل الضو"      eleven words are left over; the
                                             message is past the length bound;
                                             and it carries narration markers.
                                             Three independent reasons, any one
                                             of which is enough on its own.

  A story that *ends* in the exact words "شغل الضو" and contains nothing else is
  not a story.

* **It fails open, never closed.** Every uncertainty — a word left over, two
  devices whose labels both match, a control type whose effect is not
  reversible, any exception at all — returns None and the model decides. The
  cost of being wrong in that direction is the latency this module exists to
  remove; the cost in the other direction is acting on something nobody asked
  for. They are not traded against each other.

WHAT IT WILL NOT TOUCH
----------------------
* `ir` devices — the payload is a recorded code, and what it does in the room is
  not knowable from here.
* `text` devices — free text on her face is not a command with a closed set.
* `enum` devices — the values are the owner's own vocabulary, so "on" may mean
  something other than on.
* Anything in `guards.DESTRUCTIVE_TOOLS`. Nothing here can reach one, because
  the only tool this module ever names is `device_control`; the assertion in
  `_tool_call` keeps that true if somebody extends it.
* A turn carrying a pending confirmation or an image. Both are conversations
  mid-sentence, and a fast answer to one word of them is how a flow derails.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.agent.guards import DESTRUCTIVE_TOOLS

logger = logging.getLogger(__name__)

# The only tool the fast path may ever name.
_FAST_TOOL = "device_control"

# Control types whose commands are a closed, reversible set. The module
# docstring says why the other three are not here.
_FAST_CONTROL_TYPES = frozenset({"switch", "dimmer", "cover", "media"})

# Bounds on what can be a bare command at all.
#
# Five words and forty characters is roomy for «ساندي شغّلي ضو الصالون» and far
# under any sentence that is telling you about something. They are a cheap first
# gate, not the real one — the real one is that the parse must consume the whole
# utterance — but they mean a long message is rejected before any tenant data is
# read, so a paragraph costs no database work.
_MAX_WORDS = 5
_MAX_CHARS = 40

# Internal punctuation means more than one clause; a quotation mark means the
# sentence is reporting what somebody else said, which is the case C8 names.
# Trailing punctuation is stripped first, so «شغّل الضو!» is still a command.
_INTERNAL_BREAKS = set('.!?؟,،;؛:"\'«»()[]\n\r')
_TRAILING = ' .!؟?،,;؛\n\r\t'

# Narration markers. These are redundant — a sentence containing one of them has
# words the parse cannot consume, so it is rejected already — and they are here
# on purpose, because a safety property with a single implementation has no way
# to fail loudly. The tests assert both reasons independently.
_NARRATION = frozenset({
    "قال", "قالت", "قلت", "قلتله", "قلتلها", "حكى", "حكا", "حكت", "حكيت",
    "حكتله", "حكتلو", "حكيتله", "كان", "كانت", "صار", "صارت", "لما", "بينما",
    "وبعدين", "بعدين", "اجا", "اجت", "راح", "راحت", "طلب", "طلبت", "سالني",
    "said", "told", "asked", "when", "then", "was", "were",
})

# Verb → the actions to try, in order. The device's own `command_payload` picks
# which one applies: "افتح" is `on` for a switch and `open` for a curtain, and
# nothing here needs to know which, because the validator that owns that answer
# is already the only thing allowed to give it.
_VERBS: Dict[str, Tuple[str, ...]] = {}


def _verb(actions: Tuple[str, ...], *forms: str) -> None:
    for form in forms:
        _VERBS[form] = actions


# Normalized forms (tashkeel stripped, أإآ→ا, ة→ه, ى→ي), so «شغّل» is "شغل".
_verb(("on", "open"),
      "شغل", "شغلي", "اشغل", "شغله", "شغلها", "ولع", "ولعي", "نور", "نوري",
      "افتح", "افتحي", "فتح", "افتحلي",
      "turn on", "switch on", "put on", "on", "open")
_verb(("off", "close"),
      "طفي", "طفيي", "اطفي", "طفا", "طفئ", "اطفئ", "طفيها", "طفيه",
      "سكر", "سكري", "اسكر", "وقف", "وقفي", "اوقف",
      "turn off", "switch off", "put off", "off", "close", "stop")

# Longest first, so "turn on" is tried before "on".
_VERB_FORMS = sorted(_VERBS, key=len, reverse=True)

# Dropped from the front of an utterance: she is being addressed, not described.
_VOCATIVES = ("يا ساندي", "ساندي", "hey sandy", "hi sandy", "sandy")

# Dropped from the front of a device name on both sides of the comparison, so
# «شغّل الضو» matches a device labelled «ضو» and one labelled «الضو» alike.
_ARTICLES = ("ال", "the ", "a ")

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
                       "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه"})
_PUNCT = re.compile(r"[^\w؀-ۿ]+", re.UNICODE)


def _normalize(text: Any) -> str:
    """Fold the spellings of one word onto each other, and nothing else.

    Deliberately not `utils/nlp_normalizer.normalize_user_message`: that one
    exists to preserve human context for a model to read, and this one exists to
    compare two strings for equality. They should not be the same function.
    """
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _TASHKEEL.sub("", s).translate(_ALEF).lower()
    s = _PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_article(word: str) -> str:
    for art in _ARTICLES:
        if word.startswith(art) and len(word) > len(art):
            return word[len(art):]
    return word


def _looks_like_prose(raw: str) -> bool:
    """True when the raw message is telling a story rather than giving an order."""
    trimmed = str(raw or "").strip().rstrip(_TRAILING)
    if any(ch in _INTERNAL_BREAKS for ch in trimmed):
        return True
    if len(trimmed) > _MAX_CHARS or len(trimmed.split()) > _MAX_WORDS:
        return True
    return any(word in _NARRATION for word in _normalize(trimmed).split())


def _split_verb(utterance: str) -> Optional[Tuple[Tuple[str, ...], str]]:
    """Split a normalized utterance into (actions, target), or None.

    The verb may lead or trail — «شغّل الضو» and «الضو شغّل» are both orders —
    and whatever is left after removing it is the target, entire. Nothing is
    searched for *inside* the utterance.
    """
    for form in _VERB_FORMS:
        if utterance.startswith(form + " "):
            return _VERBS[form], utterance[len(form) + 1:].strip()
        if utterance.endswith(" " + form):
            return _VERBS[form], utterance[: -len(form) - 1].strip()
    return None


def _candidates() -> List[Dict[str, Any]]:
    """The caller's own devices that a bare command may address.

    Tenant-scoped by `list_devices` (it reads through `scoped()`), so an
    unauthenticated or guest context sees an empty list and the fast path simply
    never fires. Nothing here widens that.
    """
    from app.features.device_store import list_devices

    return [d for d in list_devices()
            if str(d.get("control_type", "")).strip().lower() in _FAST_CONTROL_TYPES]


def _match_device(target: str, devices: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The one device whose label or slug *is* the target. None if none, or many.

    Ambiguity goes to the model on purpose: two lamps both called «ضو» is a
    question («أي واحد تقصد؟»), and `device_control` already knows how to ask it.
    A fast path that picked one would be guessing, in the dark, on the owner's
    behalf.
    """
    want = _strip_article(target)
    if not want:
        return None
    hits = [d for d in devices
            if _strip_article(_normalize(d.get("label", ""))) == want
            or _strip_article(_normalize(d.get("name", ""))) == want]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        logger.info("[fast] %r matches %d devices — leaving it to the model",
                    target, len(hits))
    return None


def _tool_call(device: Dict[str, Any], action: str) -> Dict[str, Any]:
    # Belt and braces for a module whose whole job is to skip the model's
    # judgement: if this ever names something destructive it stops being a
    # latency optimisation and becomes a way to delete data without being asked.
    assert _FAST_TOOL not in DESTRUCTIVE_TOOLS, \
        "the fast path may not name a destructive tool"
    return {
        "name": _FAST_TOOL,
        "args": {"device": device.get("name", ""), "action": action},
    }


def _enabled() -> bool:
    from app.config import SANDY_FAST_PATH

    return SANDY_FAST_PATH


def try_fast_route(state: Any) -> Optional[Dict[str, Any]]:
    """The `function_call` this turn can have without a model, or None.

    None is the answer for everything that is not unmistakable, and it is the
    answer this function is biased towards — see the module docstring.
    """
    try:
        if not _enabled():
            return None
        # A confirmation in flight, or an image on the turn, is a conversation
        # mid-sentence. Answering one word of it quickly is how a flow breaks.
        if state.get("pending_state") or state.get("image_state"):
            return None

        raw = str(state.get("message") or state.get("user_message") or "")
        if not raw.strip() or _looks_like_prose(raw):
            return None

        utterance = _normalize(raw)
        for voc in _VOCATIVES:
            if utterance.startswith(voc + " "):
                utterance = utterance[len(voc) + 1:].strip()
                break

        split = _split_verb(utterance)
        if split is None:
            return None
        actions, target = split
        if not target:
            return None

        devices = _candidates()
        if not devices:
            return None
        device = _match_device(target, devices)
        if device is None:
            return None

        # The device's own validator chooses the action, and its refusal is a
        # perfectly good outcome: an action this device does not take means the
        # sentence was not the command it looked like, so the model gets it.
        from app.features.device_store import command_payload

        for action in actions:
            if command_payload(device, action).get("ok"):
                logger.info("[fast] %r → %s(%s, %s) — no model call",
                            raw[:40], _FAST_TOOL, device.get("name"), action)
                return _tool_call(device, action)
        return None

    except Exception:  # noqa: BLE001 — an optimisation may never break a turn
        logger.warning("[fast] fast route failed; falling back to the model",
                       exc_info=True)
        return None
