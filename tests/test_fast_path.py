"""The fast path picks a device command without a model — and refuses everything else.

The case this suite exists for is the one the owner raised when the idea was
proposed: if «شغّل الضو» is enough to switch on a light, what happens the day he
tells Sandy a story that contains those words? CONVENTIONS.md C8 had already
written the same objection down as a rule. So the tests are organised around it:
the commands that must be fast, and — at greater length — the sentences that must
not be, each rejected for a reason that is checked on its own.
"""
from __future__ import annotations

import pytest

from app.agent import fast_path


# ── the tenant's registry, which is what the matcher is built from ───────────
_DEVICES = [
    {"name": "living_light", "label": "الضو", "control_type": "switch", "meta": {}},
    {"name": "fan", "label": "المروحة", "control_type": "switch", "meta": {}},
    {"name": "curtain", "label": "الستارة", "control_type": "cover", "meta": {}},
    {"name": "music", "label": "الموسيقى", "control_type": "media", "meta": {}},
    {"name": "ac_mode", "label": "المكيف", "control_type": "enum",
     "meta": {"values": ["cool", "heat"]}},
    {"name": "tv", "label": "التلفزيون", "control_type": "ir",
     "meta": {"buttons": {"on": "0x1", "off": "0x2"}}},
    {"name": "face_text", "label": "الشاشة", "control_type": "text", "meta": {}},
]


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    """Stand in for the tenant's own devices, tenant-scoped in production."""
    monkeypatch.setattr("app.features.device_store.list_devices", lambda: _DEVICES)


def _route(message, **state):
    state.setdefault("message", message)
    return fast_path.try_fast_route(state)


# ── what must be fast ────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, device, action", [
    ("شغل الضو", "living_light", "on"),
    ("شغّل الضو", "living_light", "on"),          # tashkeel
    ("شغلي الضو", "living_light", "on"),
    ("ولع الضو", "living_light", "on"),
    ("طفي الضو", "living_light", "off"),
    ("اطفي المروحة", "fan", "off"),
    ("شغل الضو!", "living_light", "on"),          # trailing punctuation only
    ("ساندي شغلي الضو", "living_light", "on"),    # vocative
    ("يا ساندي طفي الضو", "living_light", "off"),
    ("شغل ضو", "living_light", "on"),             # article on one side only
    ("الضو شغل", "living_light", "on"),           # verb trailing
    ("turn on the fan", "fan", "on"),
    ("افتح الستارة", "curtain", "open"),          # cover → open, not on
    ("سكر الستارة", "curtain", "close"),
    ("شغل الموسيقى", "music", "on"),
])
def test_a_bare_command_needs_no_model(message, device, action):
    call = _route(message)
    assert call is not None, f"{message!r} should have been answered without a model"
    assert call["name"] == "device_control"
    assert call["args"] == {"device": device, "action": action}


# ── the story. The whole reason for the conditions ───────────────────────────

def test_the_story_that_ends_in_the_command_does_not_fire():
    """The owner's own example, in his words.

    A keyword search finds «شغل الضو» in here and turns the light on in the
    middle of a conversation. The whole-utterance rule does not, because the
    other eleven words have nowhere to go.
    """
    story = ("كان اخوي بحكي معي وطولنا بالحكي فاجا اخوي الصغير وحكتلو شغل الضو وبس")
    assert _route(story) is None


@pytest.mark.parametrize("message", [
    "حكتلو شغل الضو",                       # reported speech, short enough to worry
    "قلتله شغل الضو",
    "قال شغل الضو",
    "لما اجا شغل الضو",
    'قال "شغل الضو"',                        # quoted
    "شغل الضو، وبعدين طفيه",                 # two clauses
    "ما تشغل الضو",                          # negation: an unconsumed word
    "بدي اشغل الضو بكرا",                    # not now
    "شو رايك نشغل الضو",                     # a question
    "he told him to turn on the fan",
    "I was going to turn on the fan",
])
def test_anything_that_is_not_an_order_goes_to_the_model(message):
    assert _route(message) is None, f"{message!r} must not be answered deterministically"


def test_the_story_is_rejected_for_three_separate_reasons():
    """Each guard is checked on its own, because a safety property with one
    implementation has no way to fail loudly. If a later change loosens the
    length bound, this test still fails on the other two."""
    story = "كان اخوي بحكي معي وطولنا بالحكي فاجا اخوي الصغير وحكتلو شغل الضو وبس"

    # 1. too long to be an order
    assert len(story.split()) > fast_path._MAX_WORDS

    # 2. it carries narration markers
    words = set(fast_path._normalize(story).split())
    assert words & fast_path._NARRATION

    # 3. and even with both bounds lifted, the parse cannot consume it
    assert fast_path._split_verb(fast_path._normalize(story)) is None


def test_an_internal_full_stop_is_prose_even_when_short():
    assert fast_path._looks_like_prose("طفيه. شغل الضو")
    assert not fast_path._looks_like_prose("شغل الضو.")


# ── what it refuses on purpose ───────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "شغل التلفزيون",     # ir — a recorded code, effect unknown from here
    "شغل الشاشة",        # text — free text on her face is not a closed set
    "شغل المكيف",        # enum — "on" is not necessarily in the owner's values
])
def test_control_types_whose_effect_is_not_a_closed_set_are_left_to_the_model(message):
    assert _route(message) is None


def test_an_unregistered_device_is_left_to_the_model():
    """`device_control` answers this with the list of real devices and a
    question. Guessing here would replace that with silence."""
    assert _route("شغل السخان") is None


def test_two_devices_with_the_same_label_are_a_question_not_a_guess(monkeypatch):
    monkeypatch.setattr("app.features.device_store.list_devices", lambda: [
        {"name": "light_a", "label": "الضو", "control_type": "switch", "meta": {}},
        {"name": "light_b", "label": "ضو", "control_type": "switch", "meta": {}},
    ])
    assert _route("شغل الضو") is None


def test_no_devices_means_no_fast_path():
    with pytest.MonkeyPatch.context() as m:
        m.setattr("app.features.device_store.list_devices", lambda: [])
        assert _route("شغل الضو") is None


def test_a_pending_confirmation_suspends_it():
    """A confirmation in flight is a conversation mid-sentence."""
    assert _route("شغل الضو", pending_state={"type": "tool_guard"}) is None


def test_an_image_turn_suspends_it():
    assert _route("شغل الضو", image_state={"b64": "..."}) is None


def test_the_kill_switch_works(monkeypatch):
    monkeypatch.setattr("app.config.SANDY_FAST_PATH", False)
    assert _route("شغل الضو") is None


def test_it_never_raises(monkeypatch):
    """An optimisation that can break a turn is not an optimisation."""
    def _boom():
        raise RuntimeError("Mongo is having a day")
    monkeypatch.setattr("app.features.device_store.list_devices", _boom)
    assert _route("شغل الضو") is None


# ── the boundary it must not cross ───────────────────────────────────────────

def test_it_can_only_ever_name_one_tool_and_that_tool_is_not_destructive():
    from app.agent.guards import DESTRUCTIVE_TOOLS

    assert fast_path._FAST_TOOL == "device_control"
    assert fast_path._FAST_TOOL not in DESTRUCTIVE_TOOLS

    src = (__import__("pathlib").Path(fast_path.__file__)).read_text(encoding="utf-8")
    body = src.split('_FAST_TOOL = ')[1]
    assert '"name": _FAST_TOOL' in body, \
        "the tool name must come from the single constant, never a literal"


def test_it_picks_but_never_executes():
    """The call it returns is handed to the ordinary dispatcher. If this module
    ever grows a `send`/`publish`/`set_state` call it has stopped being a router
    and started being a second, unguarded actuation path."""
    from pathlib import Path

    src = Path(fast_path.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    code = code.split('"""', 2)[-1]          # drop the module docstring
    for forbidden in ("set_state", "send_to_topic", "apply_actions", "publish"):
        assert forbidden not in code, f"the fast path must not call {forbidden}"


def test_both_routes_derive_the_same_fields():
    """The fast path hands over a tool call and nothing else; every other field
    the graph reads is derived by `apply_routing_decision`, for both callers.
    Copying those lookups would drift, and the symptom would be Sandy wearing
    the wrong face for a command she carried out correctly."""
    from app.agent.agents.fc_router import apply_routing_decision
    from app.agent.graph.state import create_initial_state

    state = create_initial_state(message="شغل الضو", user_id="u1", chat_id="u1")
    call = fast_path.try_fast_route(dict(state))
    assert call is not None
    routed = apply_routing_decision(state, call, routed_by="fast_path")

    assert routed["function_call"] == call
    assert routed["routed_by"] == "fast_path"
    for field in ("intent", "routing_hint", "mood", "sandy_face", "persona_intensity"):
        assert routed.get(field), f"{field} was not derived for the fast route"


# ── the claim itself: the model is not called ────────────────────────────────

def test_a_fast_turn_never_reaches_the_router(monkeypatch):
    """The point of the whole module, asserted rather than assumed.

    `_route_intent` is where a turn spends its first model call. This replaces
    `route_with_fc` with something that fails the test if it is reached at all,
    so "no model call" is checked by the suite instead of by reading the code.
    """
    from app.agent.graph import graph as graph_mod

    def _must_not_run(*_a, **_k):
        raise AssertionError("route_with_fc was called on a fast-path turn")

    monkeypatch.setattr("app.agent.agents.fc_router.route_with_fc", _must_not_run)

    from app.agent.graph.state import create_initial_state
    state = create_initial_state(message="شغل الضو", user_id="u1", chat_id="u1")
    routed = graph_mod._route_intent(state)

    assert routed["routed_by"] == "fast_path"
    assert routed["function_call"]["name"] == "device_control"


def test_an_ordinary_turn_still_reaches_the_router(monkeypatch):
    """The other half, so a fast path that silently swallowed everything would
    not pass this file."""
    from app.agent.graph import graph as graph_mod

    seen = {}

    def _fake(state, declarations):
        seen["called"] = True
        return state

    monkeypatch.setattr("app.agent.agents.fc_router.route_with_fc", _fake)

    from app.agent.graph.state import create_initial_state
    state = create_initial_state(message="كيفك اليوم يا ساندي؟",
                                 user_id="u1", chat_id="u1")
    graph_mod._route_intent(state)
    assert seen.get("called"), "an ordinary sentence must still go to the model"
