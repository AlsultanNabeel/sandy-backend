"""Every route a client still calls stays registered, with the methods it uses.

The iPhone app, the boards, the RevenueCat webhook and the firmware publish
script are the only callers; the old per-feature routes are gone (phase 5).
"""

from __future__ import annotations

import pytest

from app.api.server import create_app

KEPT = {
    "/api/account": {"GET", "DELETE"},
    "/api/account/reset": {"POST"},
    "/api/agent": {"POST"},
    "/api/agent/stream": {"POST"},
    "/api/analyze-image": {"POST"},
    "/api/auth/apple": {"POST"},
    "/api/auth/email/login": {"POST"},
    "/api/auth/email/register": {"POST"},
    "/api/auth/google": {"POST"},
    "/api/conversations": {"GET", "POST"},
    "/api/conversations/<cid>": {"GET", "PATCH", "DELETE"},
    "/api/conversations/<cid>/messages": {"POST"},
    "/api/conversations/search": {"GET"},
    "/api/daily-nudge": {"GET"},
    "/api/daily-nudge/answer": {"POST"},
    "/api/devices": {"GET", "POST"},
    "/api/devices/<name>": {"PATCH", "DELETE"},
    "/api/devices/<name>/control": {"POST"},
    "/api/devices/<name>/image": {"POST"},
    "/api/devices/<name>/ir-learn": {"POST"},
    "/api/entries": {"GET", "POST"},
    "/api/entries/<entry_id>": {"PATCH", "DELETE"},
    "/api/items": {"GET", "POST"},
    "/api/items/lists": {"GET"},
    "/api/items/<item_id>": {"PATCH", "DELETE"},
    "/api/schedules": {"GET", "POST"},
    "/api/schedules/<schedule_id>": {"PATCH", "DELETE"},
    "/api/schedules/<schedule_id>/snooze": {"POST"},
    "/api/kinds": {"GET"},
    "/api/summary": {"POST"},
    "/api/features": {"GET"},
    "/api/image": {"POST"},
    "/api/image/edit": {"POST"},
    "/api/life/focus": {"GET"},
    "/api/life/focus/history": {"GET"},
    "/api/life/focus/start": {"POST"},
    "/api/life/focus/stop": {"POST"},
    "/api/life/scenes": {"GET", "POST"},
    "/api/life/scenes/actions": {"POST"},
    "/api/life/scenes/apply": {"POST"},
    "/api/life/scenes/delete": {"POST"},
    "/api/nodes": {"GET"},
    "/api/nodes/<node_id>": {"PATCH", "DELETE"},
    "/api/nodes/<node_id>/ir/last": {"GET"},
    "/api/nodes/<node_id>/ir/learn": {"POST"},
    "/api/nodes/<node_id>/snapshot": {"POST"},
    "/api/nodes/<node_id>/snapshot/<req_id>": {"GET"},
    "/api/nodes/<node_id>/wifi": {"POST"},
    "/api/nodes/pair": {"POST"},
    "/api/nodes/pair/confirm": {"POST"},
    "/api/onboarding": {"GET", "POST"},
    "/api/persona": {"GET", "POST"},
    "/api/photos": {"GET", "POST"},
    "/api/photos/<photo_id>": {"DELETE"},
    "/api/photos/<photo_id>/file": {"GET"},
    "/api/photos/albums": {"GET"},
    "/api/push/register": {"POST"},
    "/api/push/unregister": {"POST"},
    "/api/research": {"GET"},
    "/api/subscription": {"GET"},
    "/api/voice/tts": {"POST"},
    "/api/weather": {"GET"},
    # The boards and the firmware tooling.
    "/voice": {"GET"},
    "/api/cam/upload": {"POST"},
    "/api/firmware/manifest": {"GET"},
    "/api/firmware/image/<version>": {"GET"},
    "/api/firmware/publish": {"POST"},
    "/api/firmware/rollout": {"POST"},
    "/webhook/revenuecat": {"POST"},
}

GONE = (
    "/api/tasks", "/api/reminders", "/api/life/habits", "/api/life/expenses",
    "/api/life/journal", "/api/life/shopping", "/api/life/books", "/api/goals",
    "/api/future-messages", "/api/gifts", "/api/insights/weekly", "/api/timeline",
    "/api/share/saved", "/api/plans", "/api/memory", "/api/guest-usage/status",
    "/api/chat/history",
)


@pytest.fixture(scope="module")
def rules():
    app = create_app()
    out = {}
    for r in app.url_map.iter_rules():
        out.setdefault(r.rule, set()).update(r.methods - {"HEAD", "OPTIONS"})
    return out


@pytest.mark.parametrize("path", sorted(KEPT))
def test_a_route_a_client_calls_is_registered(rules, path):
    assert path in rules, f"{path} is gone but a client still calls it"
    assert KEPT[path] <= rules[path], f"{path} lost {KEPT[path] - rules[path]}"


@pytest.mark.parametrize("path", GONE)
def test_an_old_feature_route_is_gone(rules, path):
    assert path not in rules
