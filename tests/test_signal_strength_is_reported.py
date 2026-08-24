"""«صوتي ما عم يوصل» — and the one number that says why.

The board tells the owner the link is too slow to carry her voice. That warning
has at least three causes which look identical on her face: a weak radio link, a
busy server, and a board that cannot encode fast enough. The signal strength
separates the first from the other two immediately — below roughly -75 dBm the
link cannot carry real-time audio no matter how healthy everything else is.

The camera and the room node had been reporting it for a while. The brain — the
only board that carries live audio, and so the only one where it matters — was
not. Diagnosing "slow net" therefore meant guessing between the router, the
server and the code, which is the same shape of problem as the disconnect reason
that was being logged and thrown away.
"""

from __future__ import annotations

import os
from pathlib import Path

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-rssi")

from app.features import node_store  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def as_tenant(tenant_id):
    return active_user_profile_context(
        {"chat_id": tenant_id, "permissions": "all", "relation": "user"}
    )


@pytest.fixture()
def db():
    database = mongomock.MongoClient().db
    node_store.init_node_store(database)
    return database


def test_the_brain_reports_signal_strength_in_its_heartbeat():
    fw = _read("firmware/brain-core/main/sandy_mqtt.c")
    assert '\\"rssi\\":%d' in fw, "the brain's heartbeat carries no signal strength"
    assert "wifi_sandy_rssi()" in fw


def test_the_slow_link_warning_carries_the_numbers_that_explain_it():
    """A warning that names the symptom and not the measurement sends the reader
    to the wrong layer. The queue depth and the signal strength are the two that
    decide which layer it is."""
    voice = _read("firmware/brain-core/main/sandy_voice.c")
    assert "audio backing up:" in voice
    assert "wifi_sandy_rssi()" in voice
    assert "queued" in voice


def test_signal_strength_survives_the_heartbeat_allowlist(db):
    """node_store keeps only the telemetry keys it recognises, so a field the
    firmware sends and the allowlist has never heard of is dropped in silence —
    the board reports it, the app never sees it, and nothing errors."""
    with as_tenant("tenant-a"):
        node_store.pair_node("8421", label="ساندي")
        node_store.ingest_status("8421", telemetry={"rssi": -77, "ip": "192.168.8.103"})
        node = node_store.get_node("8421") or {}
        assert node["telemetry"]["rssi"] == -77, "signal strength was filtered out"


def test_each_board_keeps_its_own_signal_strength(db):
    """Three boards share a node id. A single `rssi` field written by all of them
    would flip between them every five seconds and mean nothing — the same bug
    the camera's address already had."""
    assert "room_rssi" in node_store._TELEMETRY_KEYS

    ino = _read("room-node/room-node.ino")
    assert '\\"rssi\\"' in ino, "the room node stopped reporting its own"

    ingest = _read("cloud/app/integrations/mqtt_ingest.py")
    room = ingest[ingest.index("def _ingest_room_status"):]
    assert 'f"room_{k}"' in room, "the room node's telemetry is not namespaced"
    assert '"rssi"' in room.split("telemetry=")[1][:200]

def test_the_warning_distinguishes_a_weak_radio_from_a_stalled_link():
    """The old single state told the owner to move closer to the router. When
    the signal is strong that is worse than silence: it sends them to fix the
    one part that is working, and the robot looks wrong about its own house."""
    status_h = _read("firmware/brain-core/main/include/sandy_status.h")
    assert "SANDY_ST_LINK_STALL" in status_h

    table = _read("firmware/brain-core/main/sandy_status.c")
    assert "LINK STALL" in table
    # Only the weak-signal state may tell them to move the robot.
    weak = table[table.index("SANDY_ST_NET_SLOW"):table.index("SANDY_ST_LINK_STALL")]
    stall = table[table.index("[SANDY_ST_LINK_STALL]"):]
    assert "قرّبني ع الراوتر" in weak
    assert "قرّبني ع الراوتر" not in stall.split("},")[0]

    voice = _read("firmware/brain-core/main/sandy_voice.c")
    assert "TX_WEAK_RSSI_DBM" in voice
    assert "weak ? SANDY_ST_NET_SLOW : SANDY_ST_LINK_STALL" in voice


def test_audio_dropped_waiting_for_the_socket_is_counted():
    """The chunk is already out of the stream buffer when the socket is busy, so
    giving up does not delay it — it deletes it, and the sentence reaches the
    server with a hole in it. That path was silent, and it is the shape of "she
    cut off mid-word on a perfectly good network"."""
    voice = _read("firmware/brain-core/main/sandy_voice.c")
    assert "s_tx_lock_drops" in voice
    lock = voice[voice.index("xSemaphoreTake(s_ws_mutex, pdMS_TO_TICKS(50))"):][:300]
    assert "s_tx_lock_drops++" in lock, "the drop is still invisible"
