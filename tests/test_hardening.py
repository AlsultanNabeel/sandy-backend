"""Hardening: user text is never a regex, and every list read has a ceiling."""


# ── Text search must not be a regular expression the user wrote ──────────────

def test_a_habit_named_with_regex_characters_matches_only_itself():
    """The user's text goes into a regex, so it has to be escaped.

    Unescaped, a habit named `.*` matches every habit, and a name like `(a+)+$`
    can hang the matcher on a long string — a denial of service written by
    somebody who was only naming a habit.
    """
    from app.utils.text_query import contains, equals

    q = contains("name", ".*")
    assert q["name"]["$regex"] == r"\.\*"

    q = contains("name", "(a+)+$")
    assert "(" not in q["name"]["$regex"].replace(r"\(", "")

    # Exact match stays anchored, so a substring cannot satisfy it.
    q = equals("title", "Hobbit")
    assert q["title"]["$regex"].startswith("^") and q["title"]["$regex"].endswith("$")


def test_list_reads_all_have_a_ceiling():
    """Every list-returning query is capped; every aggregate deliberately is not.

    The distinction is the point. A cap on a list is a safety net — the caller
    gets fewer rows and the request survives. A cap on a sum is a wrong number
    that looks right, which is worse than a slow query. So the aggregates in
    reading_store carry a comment saying why they are uncapped, and this test
    exists so nobody "fixes" them later without reading it.
    """
    import re
    from pathlib import Path

    features = Path(__file__).resolve().parent.parent / "cloud" / "app" / "features"
    offenders = []
    for path in sorted(features.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        lines = src.split("\n")
        for m in re.finditer(r'\.find\(', src):
            if src[m.start() - 4:m.start() + 5] == "find_one":
                continue
            # Read the whole chained expression rather than a fixed window. A
            # regex over the chain broke on queries containing brackets
            # (str(user_id), _now()), and a character window broke on a query
            # formatted across eight lines — both reported caps that were there.
            # Walking the brackets is the only version that is simply correct.
            depth, i, n = 0, m.end() - 1, len(src)
            while i < n:
                if src[i] in "([{":
                    depth += 1
                elif src[i] in ")]}":
                    depth -= 1
                    if depth == 0:
                        # End of find(...); keep going while the chain continues.
                        rest = src[i + 1:i + 2]
                        if rest != ".":
                            j = i + 1
                            while j < n and src[j] in " \t\n":
                                j += 1
                            if src[j:j + 1] != ".":
                                break
                i += 1
            expr = src[m.start():i + 1]
            if ".limit(" in expr:
                continue
            lineno = src[: m.start()].count("\n")
            context = "\n".join(lines[max(0, lineno - 3):lineno])
            if "بلا سقف" in context or "بلا .limit()" in context:
                continue
            offenders.append(f"{path.name}:{lineno + 1}")

    assert not offenders, (
        "Uncapped find() with no stated reason: " + ", ".join(offenders) +
        "\nEither add .limit(), or add a comment above it saying why a cap "
        "would produce a wrong answer."
    )
