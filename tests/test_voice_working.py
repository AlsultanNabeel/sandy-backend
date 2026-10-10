"""While a tool runs on a call, the device hears «working» again and again (session.py).

The robot ends a call after eight seconds with neither voice; a web search takes three to eight
and a picture ten to thirty. Each «working» keeps its call open, so the frame has to repeat for as
long as the tools run, and stop when they return.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

from app.api.voice_ws import session  # noqa: E402


def test_working_repeats_until_the_tools_return():
    sent = []

    async def send_msg(m):
        sent.append(m)

    async def run():
        keep = asyncio.ensure_future(session._keep_saying_working(send_msg, every=0.01))
        await asyncio.sleep(0.055)
        keep.cancel()
        count = len(sent)
        await asyncio.sleep(0.03)
        return count

    count = asyncio.run(run())
    assert count >= 4
    assert len(sent) == count                      # nothing after the cancel
    assert all(m == {"type": "working"} for m in sent)


def test_the_interval_is_well_inside_the_robots_idle_limit():
    # VOICE_SESSION_IDLE_MS on the board is 8 s.
    assert session._WORKING_EVERY_S <= 4.0


def test_working_goes_to_every_channel_not_only_the_app():
    src = Path(session.__file__).read_text(encoding="utf-8")
    start = src.index("if response.tool_call:")
    block = src[start:src.index("send_tool_response", start)]
    assert '{"type": "working"}' in block
    assert "_APP_CHANNEL" not in block
