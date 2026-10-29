"""The broker listener keeps listening, and says when it does not.

Heartbeats repeat every five seconds, so one worker that hears them keeps the registry
looking fresh while the other is deaf: a listener that gave up at boot, a refused
subscription or a handler that throws all look like a healthy robot. These pin the
pieces that make such a failure visible.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

_SRC = (Path(__file__).resolve().parent.parent
        / "cloud/app/integrations/mqtt_ingest.py").read_text(encoding="utf-8")


def test_a_bad_minute_at_boot_does_not_deafen_a_worker_forever():
    """The listener must keep trying, not give up once.

    A dyno boots every deploy and every daily cycle. If DNS or TLS is slow for
    the two seconds we happen to ask, that worker never listens again — and
    nothing in the logs says so, because the other worker keeps the registry
    looking alive.
    """
    assert "connect_async(" in _SRC, (
        "back to a blocking connect — one bad boot silently disables inbound "
        "MQTT for the whole life of that worker")
    assert "reconnect_delay_set(" in _SRC, (
        "no retry backoff configured, so a reconnect storm is one outage away")


def test_the_client_id_cannot_collide_between_dynos():
    """`sandy-ingest-<pid>` was not unique and pids are not random.

    Every container has its own pid namespace, so gunicorn's workers get the
    same low numbers in every dyno — and Heroku runs the new dyno alongside the
    old one during a deploy. Two connections with one client id is a fight the
    broker ends by kicking one off; it reconnects and kicks the other. Repeated
    heartbeats ride that out, and a command reply in between is lost.
    """
    assert "uuid.uuid4()" in _SRC, (
        "the ingest client id is derived from the pid alone again — it will "
        "collide across dynos during a deploy overlap")


def test_a_dropped_connection_is_not_silent():
    assert "on_disconnect" in _SRC, (
        "a drop leaves no trace, and silence is indistinguishable from working")


def test_the_broker_is_asked_whether_it_granted_the_subscription():
    """`subscribe()` returning is not the broker agreeing.

    The call returns once the packet is written; the answer arrives later, per
    topic, and a refusal is 128. Three subscriptions can be granted and the
    fourth denied with nothing in the logs. That is indistinguishable from a
    board that never published.
    """
    assert "on_subscribe" in _SRC, "the SUBACK is still ignored"
    assert ">= 128" in _SRC, "a refused subscription is not detected"


def test_the_listener_counts_what_it_hears():
    """Counters, because "connected" was never the question.

    Every layer can look healthy while nothing arrives. What is missing then is a
    number: heartbeats and IR codes heard on this worker. One at zero names the fault.
    """
    from app.integrations.mqtt_ingest import get_ingest_stats

    s = get_ingest_stats()
    for key in ("status", "ir", "disconnects",
                "errors", "pid", "connected", "granted_qos"):
        assert key in s, f"/api/diagnose would not report {key}"


def test_a_handler_that_throws_is_not_hidden_at_debug_level():
    """A raising handler and an uncalled handler look identical from outside.

    This was logged at DEBUG, which on a production log level is the same as not
    logging at all — so "every message fails" and "no messages arrive" produced
    the same evidence: silence.
    """
    assert 'logger.debug("[mqtt_ingest] message handling failed' not in _SRC


def test_a_listener_that_hears_nothing_is_rebuilt():
    """The failure that reported itself as healthy from every angle.

    Measured in production: `connected=True`, `drops=0`, `errors=0`, and
    `status=0 ir=0` — not one message in four minutes,
    while the robot heartbeat every five seconds. paho sets the connected flag on
    CONNACK and clears it from the network loop, so a dead loop thread leaves the
    flag true forever. The client lied politely for the life of the dyno.

    Silence is unambiguous here: the hardware never stops talking. Ninety seconds
    is eighteen missed heartbeats, which nothing healthy resembles.

    It rebuilds rather than reconnects, because `reconnect()` on a client whose
    thread is gone is handed to a corpse and returns without error — which is
    precisely how this stayed hidden.
    """
    assert "_watchdog" in _SRC, "nothing notices a listener that stops listening"
    assert "loop_stop()" in _SRC and "loop_start()" in _SRC, (
        "the watchdog reconnects instead of rebuilding, which cannot revive a "
        "dead network thread")
    assert "_WATCHDOG_SILENCE_S" in _SRC


def test_reading_the_suback_cannot_kill_the_network_thread():
    """A callback that raises takes the thread with it.

    `reason_codes` holds ReasonCode objects, not ints. `int(r)` on one is a small
    assumption, and small assumptions inside paho callbacks do not raise errors
    you can see — they stop delivery permanently and leave `connected=True`.
    """
    assert "getattr(r, \"value\", r)" in _SRC, (
        "SUBACK parsing assumes a type again")
    assert "could not read SUBACK" in _SRC, (
        "no guard around SUBACK parsing — an exception here silently ends "
        "message delivery for the whole worker")


class _Stop(Exception):
    pass


def _watch_once(monkeypatch, caplog, **stats):
    """One watchdog pass on a listener silent for long, with ``stats`` set; what it logged."""
    import logging
    import time
    from types import SimpleNamespace as NS

    import app.integrations.mqtt_ingest as M

    fake = NS(is_connected=lambda: True, loop_stop=lambda: None, disconnect=lambda: None)
    passes = []

    def sleep(_seconds):
        # One pass, then out of the endless loop.
        if passes:
            raise _Stop
        passes.append(1)
    monkeypatch.setattr(M.time, "sleep", sleep)
    monkeypatch.setattr(M, "_client", fake)
    monkeypatch.setattr(M, "_new_client", lambda *a: fake)
    monkeypatch.setattr(M, "_stats", {"last_message_at": time.time() - 1000, "rebuilt_at": 0,
                                      "silent_streak": 0, **stats})
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.integrations.mqtt_ingest"):
        try:
            M._watchdog("h", 1, "u", "p")
        except _Stop:
            pass
    return [r for r in caplog.records if "heard nothing" in r.getMessage()]


def test_silence_with_no_robot_is_information_not_an_error(monkeypatch, caplog):
    # «heard nothing» went to Sentry as an error every two minutes with no robot on
    # (29 Oct 2026): with no board heard since the last rebuild, silence is the normal state.
    said = _watch_once(monkeypatch, caplog)
    assert [r.levelname for r in said] == ["INFO"]


def test_a_robot_that_was_beating_and_went_quiet_is_an_error(monkeypatch, caplog):
    import time
    said = _watch_once(monkeypatch, caplog, board_heard_at=time.time() - 1000)
    assert [r.levelname for r in said] == ["ERROR"]


def test_a_retained_heartbeat_replayed_on_connect_is_no_robot(monkeypatch):
    # The broker replays each board's last heartbeat on every (re)subscribe, however old:
    # that is not a robot beating, or every rebuild would be an error again.
    from types import SimpleNamespace as NS

    import app.integrations.mqtt_ingest as M

    monkeypatch.setattr(M, "_stats", dict(M._stats))
    monkeypatch.setattr(M, "_INGEST", NS(_work_queue=NS(qsize=lambda: 0), submit=lambda *a: None))
    M._stats.pop("board_heard_at", None)
    M._on_message(None, None, NS(topic="sandy/node/x/status", payload=b"{}", retain=True))
    assert M._stats.get("board_heard_at") is None
    M._on_message(None, None, NS(topic="sandy/node/x/status", payload=b"{}", retain=False))
    assert M._stats.get("board_heard_at")
