"""Regressions for batch six: what the phone does when the network blinks.

The app had **no retry anywhere** and used `URLSession.shared` with its default
configuration, so the most ordinary thing a phone does — moving from Wi-Fi to
cellular — surfaced as `تعذّر الاتصال بالخادم` on a device that was about to be
online a second later. One dropped packet was a red banner.

These are text tests over Swift sources, and they say so: there is no Swift
runtime in this suite. The compiler gate is in CI (`ios` job,
`swiftc -typecheck` over every source), and it is what catches a broken change;
these catch the *policy* coming undone — a new call site reaching for the shared
session, or the retry being dropped in a refactor.
"""
from __future__ import annotations

import pathlib
import re

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
IOS = ROOT / "ios" / "SandyApp"
CLIENT = IOS / "Core/Networking/APIClient.swift"


def _swift_sources():
    return [p for p in IOS.rglob("*.swift") if " 2/" not in str(p)]


def test_the_session_does_not_wait_for_connectivity():
    """**The obvious fix here is a worse bug, and this is what stops it coming
    back.**

    `waitsForConnectivity` was in the first draft of this batch. With it on, the
    session ignores the per-request timeout during a connectivity wait, so the
    only bound left is `timeoutIntervalForResource` — which caps the *entire
    transfer*, not idle time. That leaves two settings and no good one: the
    seven-day default means an offline phone spins forever, and a low value
    cuts the chat stream and every photo upload off mid-flight. A caller asking
    for `timeout: 8` gets neither.

    The handover it was wanted for is `sendWithRetry`'s job. This asserts the
    absence, because a test that only checks what is present cannot see a
    setting somebody adds back.
    """
    src = CLIENT.read_text(encoding="utf-8")
    assert "static let session: URLSession" in src
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("///"))
    assert "waitsForConnectivity" not in code
    assert "timeoutIntervalForResource" not in code, \
        "a resource cap bounds the whole transfer — it would cut the SSE stream"
    assert "httpAdditionalHeaders" not in code, \
        "a blanket Accept header lies on the JPEG, WAV and SSE call sites"


def test_no_call_site_reaches_for_the_shared_session_by_accident():
    """**The half-applied fix is the failure mode here.**

    The base class is not the only place that builds a request: the photo
    upload, the project import and the chat byte stream each make their own,
    and a policy applied to one file and not the others is not a policy.

    `CameraView` is the one deliberate exception and carries its reason — it
    probes the robot on the local network, and `waitsForConnectivity` would
    hold a reachability check open instead of answering the question it exists
    to ask.
    """
    offenders = []
    for path in _swift_sources():
        rel = path.relative_to(IOS)
        if str(rel) == "Features/Control/CameraView.swift":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "URLSession.shared" in line and not line.lstrip().startswith("//"):
                offenders.append(f"{rel}:{i}")
    assert not offenders, f"still using the shared session: {offenders}"


def test_a_dropped_packet_is_retried_on_a_safe_method_only():
    """Retrying a POST could create the same task twice — worse than the error
    it avoids. Cancellation is a decision, not a failure, and a 500 that
    repeats is the server's problem."""
    src = CLIENT.read_text(encoding="utf-8")
    assert "sendWithRetry" in src
    assert 'idempotentMethods: Set<String> = ["GET", "HEAD"]' in src
    assert "idempotentMethods.contains(method)" in src
    assert "static let maxRetries = 2" in src, \
        "the retry count is the thing a refactor silently changes"

    retryable = re.search(r"let retryable: Set<URLError\.Code> = \[(.*?)\]",
                          src, re.S)
    assert retryable, "the retryable set is gone"
    codes = retryable.group(1)
    assert ".networkConnectionLost" in codes and ".timedOut" in codes
    # Nothing the server said, and nothing the user cancelled.
    assert ".cancelled" not in codes
    assert "try await Task.sleep" in src, \
        "the backoff is the loop's only cancellation checkpoint — `try?` " \
        "swallows it and sends another request for a screen the user left"


# ── The build gates, and what they do not cover ──────────────────────────────

WORKFLOW = ROOT / ".github/workflows/tests.yml"


def test_every_request_builder_goes_through_the_retry():
    """**The half-applied policy is this batch's own failure mode.**

    `perform` is not the only place that builds a request: the photo file GET,
    the album JSON call and the TTS download each make their own. The first
    draft moved them onto the shared session and left them bypassing the retry
    — so the single likeliest request in the app to lose a packet, a JPEG over
    cellular, got the new transport and none of the benefit.

    The chat stream is the one exception and says so: a reply that is
    half-delivered must not be started over.
    """
    for rel in ("Core/Networking/APIClient+Photos.swift",
                "Core/Networking/APIClient+Projects.swift"):
        src = (IOS / rel).read_text(encoding="utf-8")
        assert "APIClient.session.data(for:" not in src, \
            f"{rel} sends straight at the session, skipping the retry"
        assert "sendWithRetry" in src

    chat = (IOS / "Core/Networking/APIClient+Chat.swift").read_text(encoding="utf-8")
    assert "APIClient.session.bytes(for: req)" in chat
    assert "No retry on a stream" in chat, "the exception lost its reason"


def test_a_cancelled_chat_send_is_not_reported_as_a_network_failure():
    """`catch is URLError` collapsed cancellation into "check your internet".
    `perform` carries a comment about that exact spurious notice; the chat
    stream had the same bug one file away."""
    src = (IOS / "Core/Networking/APIClient+Chat.swift").read_text(encoding="utf-8")
    assert "catch is URLError" not in src
    assert "if urlError.code == .cancelled { throw urlError }" in src


@pytest.mark.parametrize("job", ["test:", "firmware:", "ios:"])
def test_ci_gates_every_language_that_is_still_in_the_tree(job):
    """Python, C and Swift each have a job that compiles or runs them. Android
    has none because there is no Android — the directory was removed and the
    work deferred (§7)."""
    assert job in WORKFLOW.read_text(encoding="utf-8")


def test_the_map_does_not_describe_an_android_app_that_is_not_here():
    """§7 described four thousand lines of Kotlin, a tab shell and eight
    mounted features. None of it is in the tree."""
    assert not (ROOT / "android").exists()
    # Every file a reader might reach for, not just the two sections that were
    # rewritten — the first pass left three contradictions in the map's own
    # defect list and five in the README, one of them a dead link.
    for rel in ("ARCHITECTURE_MAP.md", "README.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "ndroid" not in line:
                continue
            assert any(w in line for w in
                       ("deferred", "does not exist", "no `android/`",
                        "no Android", "comes back", "## 7.")), \
                f"{rel} still describes an Android app: {line.strip()!r}"
