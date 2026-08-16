#!/usr/bin/env python3
"""Catch "used before declared" in the firmware, before the compiler does.

Why this exists: I cannot compile ESP-IDF here, so every firmware edit reaches
the owner unverified. Three builds have now been broken by an identifier used
above the line that declares it — a mistake a compiler catches in a second and a
human reading a 1500-line file does not.

Why it is being rewritten: the previous version missed the very case it was
written for. It searched for `name(` — a function *call* — so it saw nothing when
a function was passed as a pointer:

    xTaskCreate(defer_task, "nvs_defer", 3072, NULL, 1, NULL);

and it only tracked functions at all, so a `static` variable used above its
definition was invisible. Both mistakes shipped in the same commit. A check that
misses the thing it was built to find is worse than no check, because it is
trusted.

So this one tracks every file-scope `static` — function or variable — and looks
for the bare identifier rather than a call, skipping comments and strings.

Usage:  python3 scripts/check_c_decl_order.py [files...]
        (no arguments = every .c file under firmware/)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A file-scope `static` definition: `static <stuff> name` followed by `(` for a
# function, or `=` / `;` / `[` for a variable.
DECL = re.compile(
    r"^static\s+(?:const\s+|volatile\s+|inline\s+)*"      # qualifiers
    r"[A-Za-z_][\w\s\*]*?"                                 # type
    r"\b(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:\(|=|;|\[)"
)


def strip_noise(line: str) -> str:
    """Blank out // comments and "string literals" so matches inside them do not count."""
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    return line.split("//", 1)[0]


def check(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").split("\n")

    # Blank out /* ... */ blocks across lines.
    lines, in_block = [], False
    for line in raw:
        out = line
        if in_block:
            out = "" if "*/" not in line else line.split("*/", 1)[1]
            in_block = "*/" not in line
        if not in_block and "/*" in out:
            head, _, tail = out.partition("/*")
            if "*/" in tail:
                out = head + tail.split("*/", 1)[1]
            else:
                out, in_block = head, True
        lines.append(strip_noise(out))

    declared: dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        m = DECL.match(line)
        if m:
            declared.setdefault(m.group("name"), i)

    problems = []
    for name, decl_line in declared.items():
        # A bare identifier, not part of a longer word. This is the fix: it
        # matches a call, a function pointer passed as an argument, and a plain
        # variable read — the previous version only matched the first.
        use = re.compile(r"\b" + re.escape(name) + r"\b")
        for i, line in enumerate(lines[: decl_line - 1], 1):
            if use.search(line):
                try:
                    shown = path.relative_to(ROOT)
                except ValueError:
                    shown = path          # a file from outside the tree, e.g. a
                                          # copy under /tmp while testing this
                problems.append(
                    f"{shown}:{i}: '{name}' used here, declared at line {decl_line}"
                )
                break
    return problems


def main(argv: list[str]) -> int:
    targets = ([Path(a) for a in argv] if argv
               else sorted((ROOT / "firmware").rglob("*.c")))
    targets = [t for t in targets if "managed_components" not in str(t)
               and "/build/" not in str(t)]

    problems = []
    for path in targets:
        problems += check(path)

    if problems:
        print("Used before declared:")
        for p in problems:
            print("  " + p)
        return 1
    print(f"declaration order OK ({len(targets)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
