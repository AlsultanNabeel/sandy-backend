"""A streamed transcript is fragments, and a fragment is not a word.

From the owner's log:

    heard='اه لي ها و خ لي ها  الا ولو يه  بت اعت ها  عاليه'

That is "اهليها وخليها الا ولويه بتاعتها عاليه" with the seams showing. Gemini
streams a transcript as a run of pieces, each being whatever part of a word was
ready, and the pieces already carry their own spaces. Joining them with a space
adds one inside every word that got split.

Arabic makes it unmissable because the letters join. In English the same bug
reads as a stray space and had been passing as a typo.

And it is not a log cosmetic: this text is what `_save_voice_turn` writes to
short- and long-term memory. Every voice turn has been stored shredded, and read
back to her later as though it were what was said.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-for-transcripts")

_ROOT = Path(__file__).resolve().parent.parent
_SESSION = _ROOT / "cloud" / "app" / "api" / "voice_ws" / "session.py"


def test_fragments_are_concatenated_not_space_joined():
    src = _SESSION.read_text(encoding="utf-8")
    assert 'user_text = "".join(_user_buf).strip()' in src, (
        "a space between fragments puts one inside every split word")
    assert 'sandy_text = "".join(_sandy_buf).strip()' in src
    assert '" ".join(_user_buf)' not in src
    assert '" ".join(_sandy_buf)' not in src


def test_the_observed_arabic_reassembles_correctly():
    """The exact fragmentation from the log, both ways round."""
    fragments = ["اه", "لي", "ها", " و", "خ", "لي", "ها", " الا", "ولو",
                 "يه", " بت", "اعت", "ها", " عاليه"]

    broken = " ".join(fragments).strip()
    fixed = "".join(fragments).strip()

    assert broken == "اه لي ها  و خ لي ها  الا ولو يه  بت اعت ها  عاليه"
    assert fixed == "اهليها وخليها الاولويه بتاعتها عاليه"

    # The give-away: the broken form has spaces the speaker never made.
    assert broken.count(" ") > fixed.count(" ")


def test_english_hides_the_same_bug():
    """Which is why it survived: it reads as a typo rather than as damage."""
    fragments = ["Do", "main", ".", " Set", " a", " remin", "der"]
    assert " ".join(fragments).strip() == "Do main .  Set  a  remin der"
    assert "".join(fragments).strip() == "Domain. Set a reminder"


def test_the_transcript_is_what_reaches_memory():
    """So a shredded transcript is a shredded memory, not just an odd log line.

    Pinned because the fix looks cosmetic and is not: the same variables are
    handed to _save_voice_turn a few lines below.
    """
    src = _SESSION.read_text(encoding="utf-8")
    i_join = src.index('user_text = "".join(_user_buf)')
    after = src[i_join:i_join + 5000]
    assert "_save_voice_turn" in after, (
        "the assembled transcript no longer reaches memory — check this test")
    call = after[after.index("_save_voice_turn"):][:200]
    assert "user_text" in call and "sandy_text" in call


def test_both_speakers_are_assembled_the_same_way():
    """Her own words go to memory too, and are streamed in fragments the same
    way. Fixing one side only would leave half the conversation shredded."""
    src = _SESSION.read_text(encoding="utf-8")
    joins = re.findall(r'(\w+)_text = "(.*?)"\.join', src)
    assert joins, "the assembly moved; this test needs updating"
    for who, sep in joins:
        assert sep == "", f"{who}_text is still joined with {sep!r}"
