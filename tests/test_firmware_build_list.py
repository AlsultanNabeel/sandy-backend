"""Every firmware source is in the build list.

A .c file that nobody added to CMakeLists is not a compile error. It is worse:
the project builds, links, and runs, and the feature simply is not there — the
functions it defines are undefined at link time only if something calls them,
and code guarded by a feature flag often is not called from anywhere else.

The file this test was written for is sandy_screen.c, added in the same commit.
Forgetting it would have shipped a display feature that built cleanly and did
nothing at all.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "firmware" / "brain-core" / "main"


def test_no_firmware_source_is_left_out_of_the_build():
    listed = set(re.findall(r'"(\w+\.c)"',
                            (MAIN / "CMakeLists.txt").read_text(encoding="utf-8")))
    on_disk = {p.name for p in MAIN.glob("*.c")}

    assert len(listed) >= 15, "the CMakeLists pattern stopped matching"

    missing = on_disk - listed
    assert not missing, (
        f"{sorted(missing)} exist but are not in CMakeLists — they will not be "
        "compiled, and the build will succeed anyway"
    )

    stale = listed - on_disk
    assert not stale, f"{sorted(stale)} are in CMakeLists and not on disk"
