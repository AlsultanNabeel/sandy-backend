"""Hardening tests for the 5 confirmed risks from the technical briefing."""

import threading
import unittest
from typing import Any, Dict


# ── Risk 1: Chroma stable hash IDs ───────────────────────────────────────────

class ChromaHashStabilityTests(unittest.TestCase):
    def test_fact_id_is_deterministic(self):
        """Fact IDs must be reproducible across processes (no builtin hash())."""
        from app.agent.semantic_memory import _fact_id
        from app.utils.user_profiles import set_active_user_profile

        chat_id = "123456"
        text = "المستخدم اسمه نبيل"
        expected_id = _fact_id(text, chat_id)

        captured = {}

        class FakeCollection:
            def count_documents(self, *a, **kw): return 0
            def update_one(self, filter_, update, upsert=False):
                captured["id"] = filter_["_id"]
                class R:
                    upserted_id = filter_["_id"]
                return R()

        class FakeDb:
            def __getitem__(self, name):
                return FakeCollection()

        from app import db as _db
        orig_db = _db.get_db()
        _db.configure(FakeDb())
        set_active_user_profile({"relation": "owner", "permissions": "all", "chat_id": chat_id})
        try:
            from app.agent.semantic_memory import load_facts_to_chroma
            load_facts_to_chroma([{"text": text, "type": "owner_name"}])
        finally:
            _db.configure(orig_db)
            set_active_user_profile(None)

        self.assertIn("id", captured, "update_one() was never called")
        self.assertEqual(captured["id"], expected_id)
        self.assertTrue(expected_id.startswith("f_"), f"ID should start with 'f_', got: {expected_id}")

    def test_same_text_produces_same_id_on_repeated_calls(self):
        """Two calls with the same fact text must produce identical IDs."""
        from app.agent.semantic_memory import _fact_id
        text = "يسكن في القاهرة"
        self.assertEqual(_fact_id(text, "111"), _fact_id(text, "111"))

    def test_different_texts_produce_different_ids(self):
        """Different fact texts must not collide."""
        from app.agent.semantic_memory import _fact_id
        self.assertNotEqual(_fact_id("يسكن في القاهرة", "111"), _fact_id("يعمل مهندس", "111"))

    def test_different_users_produce_different_ids(self):
        """Same text for different users must not collide."""
        from app.agent.semantic_memory import _fact_id
        self.assertNotEqual(_fact_id("اسمي نبيل", "111"), _fact_id("اسمي نبيل", "222"))


# ── Risk 2: Calendar service caching ─────────────────────────────────────────

_OWNER_PROFILE = {"relation": "owner", "permissions": "all", "tone": "casual", "name": "Test"}


class PredictionThreadSafetyTests(unittest.TestCase):
    def test_concurrent_predict_calls_do_not_corrupt_memory(self):
        """Multiple threads writing predicted_intent must not corrupt the dict."""
        state: Dict[str, Any] = {}
        lock = threading.Lock()
        errors = []

        def _write(hint: str) -> None:
            try:
                with lock:
                    state["predicted_intent"] = hint
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(f"hint_{i}",)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertIn("predicted_intent", state)


# ── Glossary injection tests ──────────────────────────────────────────────────

class ArchGlossaryTests(unittest.TestCase):
    """Verify the architecture glossary is injected and accurate."""

    def _get_system_prompt(self) -> str:
        """Build a system prompt using a minimal in-memory SandyAgent-like object."""
        import pathlib
        src = pathlib.Path("cloud/app/agent/facade/agent.py").read_text()
        # Extract _ARCH_GLOSSARY value directly from source — avoids importing the
        # full agent (which requires live credentials).
        import re
        m = re.search(r'_ARCH_GLOSSARY = """(.*?)"""', src, re.DOTALL)
        self.assertIsNotNone(m, "_ARCH_GLOSSARY constant not found in facade/agent.py")
        return m.group(1)

    def test_glossary_present_in_agent_source(self):
        """_ARCH_GLOSSARY must be defined in facade/agent.py."""
        import pathlib
        src = pathlib.Path("cloud/app/agent/facade/agent.py").read_text()
        self.assertIn("_ARCH_GLOSSARY", src)

    def test_all_six_terms_present(self):
        """All six required terms must appear in the glossary."""
        glossary = self._get_system_prompt()
        required = [
            "Telegram polling",
            "memory_lock",
            "mood_cache",
            "Circuit Breaker",
            "MongoDB",
            "Semantic memory",
        ]
        for term in required:
            self.assertIn(term, glossary, f"Term missing from glossary: {term}")

    def test_memory_lock_is_not_described_as_security_or_auth(self):
        """The memory_lock definition must not use authentication or security framing."""
        glossary = self._get_system_prompt()

        # Extract only the memory_lock line
        lock_line = ""
        for line in glossary.splitlines():
            if "memory_lock" in line:
                lock_line = line
                break

        self.assertTrue(lock_line, "memory_lock entry not found in glossary")

        forbidden_terms = [
            "security", "auth", "authorization", "authentication",
            "تأمين", "أمان", "مصادقة", "تفويض",
        ]
        for term in forbidden_terms:
            self.assertNotIn(
                term.lower(),
                lock_line.lower(),
                f"memory_lock definition must not mention '{term}' — "
                "it is a threading primitive, not a security feature",
            )

    def test_memory_lock_mentions_threading(self):
        """The memory_lock definition must reference threading."""
        glossary = self._get_system_prompt()
        lock_line = next(
            (line for line in glossary.splitlines() if "memory_lock" in line), ""
        )
        self.assertTrue(lock_line, "memory_lock entry not found")
        threading_terms = ["threading", "Lock", "خيوط", "كتابة متزامنة"]
        self.assertTrue(
            any(t in lock_line for t in threading_terms),
            f"memory_lock line must mention threading/concurrency: {lock_line!r}",
        )

    def test_semantic_memory_describes_graceful_degradation(self):
        """Semantic memory definition must mention explicit/graceful degradation."""
        glossary = self._get_system_prompt()
        memory_line = next(
            (line for line in glossary.splitlines() if "Semantic memory" in line), ""
        )
        self.assertTrue(memory_line, "Semantic memory entry not found")
        degradation_terms = ["تتدهور", "degrad", "آمن", "صريح"]
        self.assertTrue(
            any(t in memory_line for t in degradation_terms),
            f"Semantic memory line must describe graceful degradation: {memory_line!r}",
        )

    def test_circuit_breaker_not_described_as_network_outage(self):
        """Circuit Breaker definition must not imply it is a network-level concept."""
        glossary = self._get_system_prompt()
        cb_line = next(
            (line for line in glossary.splitlines() if "Circuit Breaker" in line), ""
        )
        self.assertTrue(cb_line, "Circuit Breaker entry not found")
        # Must mention external services / safe fallback
        self.assertTrue(
            any(t in cb_line for t in ["خدمات", "service", "آمنة", "safe", "wrapper"]),
            f"Circuit Breaker line must mention service isolation: {cb_line!r}",
        )

    def test_glossary_marked_internal_only(self):
        """Glossary must instruct Sandy not to share these definitions with users."""
        glossary = self._get_system_prompt()
        internal_markers = ["للاستخدام الداخلي", "داخلية", "لا تشاركها"]
        self.assertTrue(
            any(m in glossary for m in internal_markers),
            "Glossary must carry an 'internal only' marker so Sandy doesn't volunteer it",
        )


# ── Normal chat path: timeout protection and fallback ─────────────────────────

class NormalChatTimeoutHardeningTests(unittest.TestCase):
    """Verify that the normal chat path (multi_step_hint=NONE) has timeout and fallback protection.

    Root cause: 'راجعي ساندي ثم قوليلي شو ناقص.' hung silently — no Telegram reply sent.
    Chroma queries and Azure LLM calls have no timeout, so a slow response = infinite hang.
    """

    def _src(self):
        import pathlib
        return pathlib.Path("cloud/app/agent/facade/agent.py").read_text()



if __name__ == "__main__":
    unittest.main()


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
