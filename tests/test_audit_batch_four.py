"""Regressions for batch four of the 24 Aug 2026 audit: whose name she says.

Eight strings that reach a customer had the owner's name typed into them. The
worst is the live voice prompt — the first thing every robot in the world is
told about the person standing in front of it: *"you are in a voice conversation
with نبيل (your partner)"*, for every customer, on every call.

The fix is one function, `user_profiles.speaker_label`, reading the name the
customer typed into first-run setup. `المستخدم` when nothing is known: that is
honest, someone else's name is not, and a blank is worse than either — a prompt
that reads "in a voice conversation with " invites the model to fill the gap.

`config.py`'s mentions are deliberately untouched. *"طوّرك نبيل السلطان"* is a
developer credit and belongs to every customer; the persona line that calls her
his partner is product copy (`CONVENTIONS.md` C7) and the owner's call.
"""
from __future__ import annotations

import threading

import mongomock
import pytest


CUSTOMER = "cust-1"
PROFILE = {"user_id": CUSTOMER, "chat_id": CUSTOMER, "relation": "user",
           "permissions": "all", "is_owner": False, "is_guest": False, "name": ""}


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    database["sandy_users"].insert_one({
        "_id": CUSTOMER, "user_id": CUSTOMER,
        "onboarding": {"done": True, "preferred_name": "سامي",
                       "interests": ["كرة قدم"], "notes": ""},
    })
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


def test_a_customer_with_no_name_is_the_user_not_someone_else(db):
    """`المستخدم`, never a blank and never another person."""
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(
            {**PROFILE, "chat_id": "nameless", "user_id": "nameless"}):
        assert user_profiles.speaker_label("nameless") == "المستخدم"
    with user_profiles.active_user_profile_context(PROFILE):
        assert user_profiles.speaker_label(CUSTOMER) == "سامي"


def test_the_live_voice_prompt_names_the_customer(db):
    """**The single worst string in the system.**

    `_system_instruction_body` is what every robot is handed at the start of
    every call, and it said the person in front of it was نبيل.
    """
    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.tools as vt
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        text = vt._system_instruction_body(CUSTOMER, lambda _uid: "شخصية")

    assert "نبيل" not in text
    assert "سامي" in text


def test_the_speaker_verification_note_names_the_customer(db):
    """A customer's own robot told them «مش نبيل» after verifying their voice,
    and refused to believe they were themselves."""
    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.speaker as vs
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        verified = vs._speaker_directive(True)
        stranger = vs._speaker_directive(False)

    for text in (verified, stranger):
        assert "نبيل" not in text
    assert "سامي" in verified


def test_recalled_transcripts_attribute_turns_to_the_right_person(db):
    """Every user turn was labelled «نبيل», so the model read a customer's own
    conversation as somebody else's."""
    import app.api.voice_ws.memory as vm
    import app.features.brainstorm as bs
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        voice = vm._load_stm_context([{"role": "user", "content": "مرحبا"}])

        bs.init_brainstorm(db)
        bs.start_session(CUSTOMER, "فكرة")
        db["sandy_stm"].insert_one({
            "key": f"{CUSTOMER}:{CUSTOMER}", "user_id": CUSTOMER,
            "history": [{"role": "user", "content": "بدي أعمل مشروع"}],
        })
        captured = {}

        def _capture(messages=None, **kw):
            captured["prompt"] = "\n".join(
                str(m.get("content", "")) for m in (messages or []))

            class _C:
                class message:  # noqa: N801
                    content = "خطة"

            class _R:
                choices = [_C]

            return _R()

        bs.finish_session(CUSTOMER, create_chat_completion_fn=_capture)

    assert "نبيل" not in voice and "سامي" in voice
    assert "نبيل" not in captured.get("prompt", "")


def test_the_chat_only_refusal_names_the_account_not_the_owner(db):
    """Shown to every chat-only visitor on every tenant."""
    from app.utils import user_profiles

    line = user_profiles.build_user_profile_prompt_sections(
        {**PROFILE, "permissions": "chat-only"})["user_profile_priority_line"]
    assert "نبيل" not in line
    assert "صاحب الحساب" in line


def test_the_address_instruction_does_not_name_anyone(db):
    """Masculine is the default because Arabic forces a choice, not because the
    speaker is a particular person — it read «المالك نبيل افتراضياً»."""
    from app.utils import user_profiles

    assert "نبيل" not in user_profiles.address_instruction({})
    assert "المؤنث" in user_profiles.address_instruction({"gender": "female"})


def test_the_morning_brief_is_written_for_whoever_asked(db, monkeypatch):
    """It opened with «اكتبي ملخص صباحي … لنبيل (ذكر)» for every tenant."""
    import app.integrations.azure_intent_client as aic
    from app.agent.facade.briefing import build_morning_briefing
    from app.utils import user_profiles

    captured = {}
    monkeypatch.setattr(aic.AzureIntentClient, "__init__",
                        lambda self, *a, **kw: None)
    monkeypatch.setattr(
        aic.AzureIntentClient, "_generate_with_gemini",
        lambda self, prompt, **kw: (captured.setdefault("p", str(prompt)), "صباح")[1])

    with user_profiles.active_user_profile_context(PROFILE):
        build_morning_briefing(memory={}, mongo_db=db, tasks_file=None)

    instruction = captured["p"].split("اكتبي ملخص صباحي")[-1]
    assert "نبيل" not in instruction
    assert "سامي" in instruction


def test_the_dead_owner_device_gate_is_gone():
    """`_OWNER_DEVICE_PREFIXES = ("hardware_",)` and no registered tool has ever
    started with `hardware_`. Two branches called it, both dead, and the refusal
    one of them held named the owner to customers who could never reach it.

    The real boundary is `device_store.tenant_owns_topic` — a device belongs to
    the calling tenant's registry or it does not exist for them.
    """
    import app.agent.nodes.execute as ex
    from app.agent.tools.registry import get_registry
    from app.agent.tools.setup import register_all_tools

    assert not hasattr(ex, "_is_owner_device_tool")
    assert not hasattr(ex, "_OWNER_DEVICE_PREFIXES")

    register_all_tools()
    assert not [n for n in get_registry().all_names() if n.startswith("hardware_")], \
        "a hardware_ tool now exists — the gate deleted here may be needed again"


def test_a_voice_caller_is_a_user_not_the_owner():
    """`permissions: "all"` is right — the caller authenticated and `chat_id`
    scopes everything they touch. `relation: "owner"` was not: it said "this is
    tenant #1" and was handed to every customer who spoke to a robot."""
    import app.api.voice_ws.tools as vt

    profile = vt._voice_profile("anyone")
    assert profile["relation"] == "user"
    assert profile["permissions"] == "all"


# ── What the fix itself nearly broke ─────────────────────────────────────────

def test_a_woman_is_not_told_she_is_a_man_with_no_way_out(db):
    """**The multi-tenancy batch nearly hard-coded a gender.**

    The voice prompt used to say «الافتراضي مذكر لحد ما تتأكدي؛ إذا عرفتِ إنّ
    المتحدثة أنثى، خاطبيها بصيغة المؤنث» — a guess *with* an escape hatch.
    Replacing it with a flat `address_instruction()` deleted the hatch, and no
    production path sets `gender` on a profile, so a female customer's robot
    would have been told she was male with nothing able to change it.
    """
    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.tools as vt
    from app.utils import user_profiles

    default = user_profiles.address_instruction({})
    assert "المؤنث" in default, "the default masculine guess has no way out"

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        prompt = vt._system_instruction_body(CUSTOMER, lambda _uid: "شخصية")
    assert "المؤنث" in prompt


def test_the_anti_impersonation_line_still_says_something(db):
    """`صوته مش صوته` — "his voice is not his voice".

    Substituting a name into a *discriminating* sentence breaks it when there
    is no name: «مش المستخدم» and «حتى لو ادّعى إنه المستخدم» are self-
    contradictory, and this particular prompt is what stops someone talking
    their way into another person's memories.
    """
    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.speaker as vs
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        named = vs._speaker_directive(False)
    assert "صوته مش صوته" not in named
    assert "سامي" in named

    nameless = {**PROFILE, "chat_id": "no-name", "user_id": "no-name"}
    with user_profiles.active_user_profile_context(nameless):
        vm.set_voice_identity("no-name")
        anon = vs._speaker_directive(False)
    assert "مش المستخدم" not in anon, "a sentence that denies the speaker is 'the user'"
    assert "ادّعى إنه المستخدم" not in anon
    assert "صاحب الحساب" in anon


def test_the_relation_vocabulary_accepts_the_word_it_emits(db):
    """`build_user_profile` has emitted `relation: "user"` since the
    multi-tenant migration and `_normalize_relation` never learned it, so it
    round-tripped to `guest` — which forces `permissions` to chat-only and would
    fire the privacy refusal at a paying customer."""
    from app.utils import user_profiles

    normalized = user_profiles._normalize_profile(
        CUSTOMER, {"chat_id": CUSTOMER, "relation": "user"})
    assert normalized["relation"] == "user"
    assert normalized["permissions"] == "all"


def test_naming_the_speaker_costs_no_read_on_the_audio_path(db, monkeypatch):
    """`_speaker_directive` is awaited on the loop that relays audio, once per
    utterance. `_verify_owner` is pushed to an executor on the line above and
    `_save_voice_turn` is fire-and-forget with a comment about the pause being
    audible — a synchronous find_one here is the same stall.

    **Driven through the session, not warmed by hand.** The first version of
    this test called `voice_speaker_label()` itself — the exact step
    `_live_session` was not doing — so it proved "a warm cache stays warm"
    while the loop went on reading. Here the setup is the production one, and
    it also asserts the resolution happens *in the executor*: called straight
    on the loop it is still a blocking read, just moved from utterance one to
    session start.
    """
    import asyncio

    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.speaker as vs
    import app.features.users_store as us
    from app.utils import user_profiles

    reads = []
    monkeypatch.setattr(
        us, "get_user",
        lambda uid: reads.append((uid, threading.current_thread().name)) or
        {"onboarding": {"preferred_name": "سامي"}})

    async def _session_setup():
        # The two lines `_live_session` runs before any audio flows.
        loop = asyncio.get_event_loop()
        vm.set_voice_speaker_label(
            await loop.run_in_executor(None, vm.resolve_speaker_label, CUSTOMER))
        # …then five utterances, each ending in a directive, on this loop.
        return [vs._speaker_directive(True) for _ in range(5)]

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        out = asyncio.run(_session_setup())

    assert all("سامي" in t for t in out), "the name never reached the directive"
    assert len(reads) == 1, f"{len(reads)} reads for one session, expected 1"
    assert not reads[0][1].startswith("MainThread"), \
        "the one read happened on the loop — moved, not removed"


def test_she_answers_in_the_language_she_was_written_to(db):
    """Nothing told her which language to answer in.

    The persona is written in Levantine Arabic, so an English message got an
    Arabic reply and an English-speaking customer had a robot that would not
    talk to them. The rule is appended by code — beside the anti-injection one
    and for the same reason: it has to survive a custom persona and a Heroku
    override of `SANDY_PERSONALITY`.
    """
    from app.agent.context_builder import build_effective_persona

    persona = build_effective_persona(None)
    assert "بلغة آخر رسالة" in persona
    assert "الإنجليزي" in persona
    # Per message, not per conversation: «مرحبا» then «how are you» switches.
    assert "كل رسالة لحالها" in persona


def test_the_language_rule_reaches_voice_too(db):
    """One rule, every channel — it goes in the persona, which the voice
    instruction builds on, so it cannot apply to chat and not to the robot."""
    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.tools as vt
    from app.agent.context_builder import build_effective_persona
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        text = vt._system_instruction_body(CUSTOMER, build_effective_persona)

    assert "بلغة آخر رسالة" in text


def test_both_halves_of_the_voice_prompt_name_the_same_person(db):
    """**The rule was written into the map and broken in the same commit.**

    The standing instruction (`tools.py`) and the per-turn verification note
    (`speaker.py`) both build discriminating sentences about the same person.
    One branched on `HAS_NO_NAME` and the other substituted it, so a tenant
    with no `preferred_name` got «مش المستخدم» in one and «مش صاحب الحساب» in
    the other — two referents in one session, in the prompt whose job is to
    stop somebody talking their way into another person's memories.
    """
    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.speaker as vs
    import app.api.voice_ws.tools as vt
    from app.utils import user_profiles

    nameless = {**PROFILE, "chat_id": "no-name", "user_id": "no-name"}
    with user_profiles.active_user_profile_context(nameless):
        vm.set_voice_identity("no-name")
        standing = vt._system_instruction_body("no-name", lambda _uid: "شخصية")
        per_turn = vs._speaker_directive(False)

    for text in (standing, per_turn):
        assert "مش المستخدم" not in text
        assert "أنا المستخدم" not in text
        assert "صاحب الحساب" in text


def test_the_voice_prompt_does_not_order_a_dialect_over_the_language_rule(db):
    """`ردودك قصيرة ومباشرة وبالشامي` sat after the language rule and was more
    specific about the same decision, so an English utterance got two orders
    and the later one normally wins."""
    import app.api.voice_ws.memory as vm
    import app.api.voice_ws.tools as vt
    from app.agent.context_builder import build_effective_persona
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(PROFILE):
        vm.set_voice_identity(CUSTOMER)
        text = vt._system_instruction_body(CUSTOMER, build_effective_persona)

    assert "وبالشامي" not in text
    assert "بلغة آخر رسالة" in text


def test_no_route_still_follows_the_interface_language():
    """Two routes carried the old session-scoped policy — «reply in English
    because the site is in English» — and deleting one left the other. An
    English-interface user asking «شو في بالصورة؟» was ordered to answer their
    Arabic question in English, which is the exact failure the rule replaced.

    A substring check for one phrasing is what let the second one survive, so
    this looks for the *shape*: any branch on the interface language that then
    dictates a reply language.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/api/server.py").read_text(encoding="utf-8")
    for match in re.finditer(r'lang.{0,40}==\s*"en"', src):
        window = src[match.end():match.end() + 400]
        assert "English" not in window, (
            "a route still tells her to reply in English because the site is "
            f"in English: ...{window[:120]}")


def test_the_morning_brief_addresses_a_nameless_tenant_in_arabic(db):
    """«لـ» + «المستخدم» renders «لـالمستخدم». The lam assimilates."""
    import app.integrations.azure_intent_client as aic
    from app.agent.facade.briefing import build_morning_briefing
    from app.utils import user_profiles

    captured = {}
    with user_profiles.active_user_profile_context(
            {**PROFILE, "chat_id": "no-name", "user_id": "no-name"}):
        import pytest as _pytest
        mp = _pytest.MonkeyPatch()
        try:
            mp.setattr(aic.AzureIntentClient, "__init__",
                       lambda self, *a, **kw: None)
            mp.setattr(aic.AzureIntentClient, "_generate_with_gemini",
                       lambda self, prompt, **kw: (
                           captured.setdefault("p", str(prompt)), "صباح")[1])
            build_morning_briefing(memory={}, mongo_db=db, tasks_file=None)
        finally:
            mp.undo()

    assert "لـالمستخدم" not in captured["p"]
    assert "للمستخدم" in captured["p"]


def test_the_speaker_gate_is_told_who_it_is_verifying(db):
    """**The batch made a false positive convincing.**

    `_verify_owner` takes a `user_id` because it runs on a pool thread where the
    session context does not reach — its own docstring says so, and the other
    caller passes it. `_verify_and_inject` did not, so on a fresh pool worker
    `_stm_chat_id()` came back empty, `has_profile("")` was false, and the
    function took its "no voiceprint enrolled — allow" branch. A comparison that
    never ran returned *owner*, and this batch then had the directive announce
    it by the customer's real name.
    """
    import inspect

    import app.api.voice_ws.speaker as vs

    src = inspect.getsource(vs._verify_and_inject)
    assert "get_voice_identity()" in src, \
        "the gate runs without an identity — on a fresh pool thread it fails open"
    assert "_verify_owner, pcm, get_voice_identity()" in src


def test_the_dialect_preset_does_not_outrank_the_language_rule(db):
    """The persona says «احكي باللهجة الفلسطينية» and the rule says reply in the
    language of the message. Both are about the same decision and the dialect
    line is the more specific one, so an English-only customer on the main text
    path got two orders. The rule states its own precedence now, and says what
    the dialect line actually governs."""
    from app.agent.context_builder import LANGUAGE_RULE, build_effective_persona

    persona = build_effective_persona(None)
    assert "اللهجة الفلسطينية" in persona, "the fixture no longer covers a dialect"
    assert "بتغلب أي تعليمة لهجة" in LANGUAGE_RULE
    assert "مش بتلزمك تحكي عربي" in LANGUAGE_RULE
    assert persona.index("اللهجة الفلسطينية") < persona.index("بتغلب أي تعليمة لهجة")


def test_a_guest_cannot_be_handed_full_permissions_by_a_dict(db):
    """`active_profile_is_guest` reads permissions alone, so a profile saying
    `relation: guest, permissions: all` clears every guest gate in the system.
    A default is not a limit — the relation has to be the ceiling."""
    from app.utils import user_profiles

    for relation in ("guest", "family"):
        out = user_profiles._normalize_profile(
            "g1", {"chat_id": "g1", "relation": relation, "permissions": "all"})
        assert out["permissions"] == "chat-only", \
            f"a {relation} was handed full permissions by its own dict"

    ok = user_profiles._normalize_profile(
        "u1", {"chat_id": "u1", "relation": "user", "permissions": "all"})
    assert ok["permissions"] == "all", "an authenticated user lost their own data"


def test_a_name_that_begins_with_alef_lam_is_not_mangled(db, monkeypatch):
    """«الياس» is a name, not «ال» + «ياس». Assimilating blindly turns it into
    «للياس», which is a different person."""
    import app.integrations.azure_intent_client as aic
    import app.utils.user_profiles as up
    from app.agent.facade.briefing import build_morning_briefing

    captured = {}
    monkeypatch.setattr(aic.AzureIntentClient, "__init__",
                        lambda self, *a, **kw: None)
    monkeypatch.setattr(
        aic.AzureIntentClient, "_generate_with_gemini",
        lambda self, prompt, **kw: (captured.setdefault("p", str(prompt)), "صباح")[1])
    monkeypatch.setattr(up, "speaker_label", lambda *a, **kw: "الياس")

    with up.active_user_profile_context(PROFILE):
        build_morning_briefing(memory={}, mongo_db=db, tasks_file=None)

    assert "للياس" not in captured["p"]
    assert "الياس" in captured["p"]
