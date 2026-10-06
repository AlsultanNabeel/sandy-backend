"""The name given in first-run setup is the one Today and the chat greet with. Setup saved
it straight to the server and never into the app's state, so after a relaunch mid-setup
the greeting used no name until the next full reload. One way to save the profile:
`AppState.saveProfile`, which keeps the state in step."""
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "ios" / "SandyApp"


def test_setup_saves_the_profile_through_the_app_state():
    src = (APP / "Features/Onboarding/OnboardingView.swift").read_text(encoding="utf-8")
    assert "state.saveProfile(" in src
    assert "api.saveOnboarding(" not in src


def test_the_only_direct_save_is_the_app_state_s_own():
    callers = [p for p in APP.rglob("*.swift")
               if "api.saveOnboarding(" in p.read_text(encoding="utf-8")]
    assert [p.name for p in callers] == ["AppState.swift"]
