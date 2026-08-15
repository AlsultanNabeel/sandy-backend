"""Every string in the app exists in every language it claims to support.

This is a Python test over Swift source on purpose. The parity it checks is not
something the Swift compiler can see — `L10nTable(ar:en:)` takes two dictionaries
and is perfectly happy if one of them is missing half its keys. The failure shows
up at runtime as a raw key like `control.node.pair` rendered on screen, and only
in the language nobody on the team reads every day.

CI already runs pytest and does not build the iOS app, so putting the check here
means it runs on every push today rather than after somebody sets up Xcode in CI.

It also guards the thing that makes a second language sustainable: adding a
string in Arabic and forgetting the English one has to fail loudly, immediately,
and before it ships — otherwise the English build slowly rots into a half
translation, which is worse than being Arabic-only and honest about it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

L10N_DIR = Path(__file__).resolve().parents[1] / "ios" / "SandyApp" / "Localization"

# Every language the app ships. Adding one here makes every table below required
# to carry it — which is the point: the test is the definition of "supported".
LANGUAGES = ("ar", "en")


def table_files() -> list[Path]:
    return sorted(L10N_DIR.glob("L10n+*.swift"))


def keys_for(source: str, lang: str) -> set[str]:
    """The keys defined under `lang:` in one L10nTable literal.

    Deliberately a regex rather than a Swift parser: the shape of these files is
    fixed and mechanical, and a parser would be more code to maintain than the
    thing it checks. If the shape ever changes, this returns nothing and the test
    fails loudly — which is the right way for it to break.
    """
    m = re.search(
        lang + r":\s*\[(.*?)\n\s*\](?:,\s*\n\s*\w+:|\s*\n\s*\))",
        source,
        re.S,
    )
    if not m:
        return set()
    return set(re.findall(r'"([\w.]+)"\s*:', m.group(1)))


@pytest.mark.parametrize("path", table_files(), ids=lambda p: p.name)
def test_every_key_exists_in_every_language(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    per_lang = {lang: keys_for(source, lang) for lang in LANGUAGES}

    for lang, keys in per_lang.items():
        assert keys, (
            f"{path.name}: no keys found for '{lang}'. Either the language block "
            f"is missing, or the file's shape changed and this test needs updating."
        )

    reference = per_lang[LANGUAGES[0]]
    for lang in LANGUAGES[1:]:
        missing = sorted(reference - per_lang[lang])
        extra = sorted(per_lang[lang] - reference)
        assert not missing, (
            f"{path.name}: {len(missing)} key(s) in '{LANGUAGES[0]}' with no "
            f"'{lang}' translation — they will render as raw keys on screen: {missing[:8]}"
        )
        assert not extra, (
            f"{path.name}: {len(extra)} key(s) in '{lang}' that '{LANGUAGES[0]}' "
            f"does not have — probably a rename that only landed on one side: {extra[:8]}"
        )


@pytest.mark.parametrize("path", table_files(), ids=lambda p: p.name)
def test_no_duplicate_keys(path: Path) -> None:
    """A repeated key in a Swift dictionary literal is a crash, not a warning."""
    source = path.read_text(encoding="utf-8")
    for lang in LANGUAGES:
        m = re.search(lang + r":\s*\[(.*?)\n\s*\](?:,\s*\n\s*\w+:|\s*\n\s*\))", source, re.S)
        if not m:
            continue
        found = re.findall(r'"([\w.]+)"\s*:', m.group(1))
        dupes = sorted({k for k in found if found.count(k) > 1})
        assert not dupes, f"{path.name} [{lang}]: duplicate keys crash at launch: {dupes}"


def test_no_empty_translations() -> None:
    """An empty string is a missing translation that passes the parity check."""
    offenders = []
    for path in table_files():
        source = path.read_text(encoding="utf-8")
        for lang in LANGUAGES:
            m = re.search(lang + r":\s*\[(.*?)\n\s*\](?:,\s*\n\s*\w+:|\s*\n\s*\))", source, re.S)
            if not m:
                continue
            for key, value in re.findall(r'"([\w.]+)"\s*:\s*\.text\("([^"]*)"\)', m.group(1)):
                if not value.strip():
                    offenders.append(f"{path.name}[{lang}].{key}")
    assert not offenders, f"empty translations render as blank UI: {offenders}"


def test_the_app_has_no_arabic_left_in_swift_views() -> None:
    """Text in a view is text that cannot be translated.

    One literal Arabic string used to sit in Theme.swift, which meant the English
    build showed Arabic on that one banner. Nothing catches that by eye.
    """
    app_dir = L10N_DIR.parent
    arabic = re.compile(r'Text\(\s*"[^"]*[؀-ۿ]')
    offenders = []
    for path in app_dir.rglob("*.swift"):
        if "Localization" in path.parts or " 2" in str(path):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            if arabic.search(line):
                offenders.append(f"{path.name}:{i}")
    assert not offenders, (
        f"literal Arabic in a view — it will not translate: {offenders}"
    )
