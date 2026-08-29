"""The log that was nothing but reconnects.

Twenty minutes of production logs, a hundred and fifty lines, and every single
one of them this:

    [mqtt_ingest] worker 12 disconnected: reason=Keep alive timeout
    [mqtt_ingest] worker 12 connected, subscribe sent (rc=Success)

Both workers, every seventy seconds, indefinitely. Two things were wrong.

**The ingest ran on paho's network thread.** `_on_message` parsed the heartbeat
and called `ingest_status` inline — several Atlas round trips — and that thread
has one other job: send PINGREQ before the keepalive expires. It cannot do that
while it is waiting on a database in another continent, so the broker sees a
client that stopped pinging and drops it. Thirty-second keepalive, seventy-second
cycle: the drop, the backoff, the reconnect.

**And every drop was logged twice**, from the socket close and again from the
loop unwinding, which doubles the apparent rate of the thing being measured.

The cost was not only noise. Every drop is a window in which a command to the
robot goes nowhere, and the noise buried the sessions the owner was trying to
find in the log.
"""
from __future__ import annotations

import time


def test_the_network_thread_is_not_the_one_doing_the_work(monkeypatch):
    """`_on_message` must return promptly no matter how slow the ingest is."""
    import app.integrations.mqtt_ingest as mi

    started = []

    def _slow(topic, raw):
        started.append(threading_ident())
        time.sleep(0.4)

    def threading_ident():
        import threading
        return threading.current_thread().name

    monkeypatch.setattr(mi, "_handle_message", _slow)

    class _Msg:
        topic = "sandy/node/abc/status"
        payload = b'{"online": true}'

    caller = threading_ident()
    t0 = time.monotonic()
    mi._on_message(None, None, _Msg())
    elapsed = time.monotonic() - t0

    assert elapsed < 0.1, (
        f"_on_message blocked the network thread for {elapsed:.2f}s — this is "
        "what the broker sees as a client that stopped pinging")

    deadline = time.monotonic() + 2.0
    while not started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started, "the message was accepted and never handled"
    assert started[0] != caller, "the ingest ran on the caller's thread after all"
    assert started[0].startswith("mqtt-ingest")


def test_the_ingest_stays_in_order():
    """One worker, not the shared pool. Heartbeats and photo slices arrive in an
    order that means something: eight threads would write an older node state
    over a newer one, and hand the camera its pieces shuffled."""
    import app.integrations.mqtt_ingest as mi

    assert mi._INGEST._max_workers == 1


def test_a_stalled_database_does_not_grow_the_queue_forever(monkeypatch):
    """An unbounded queue in front of a stalled store is a slower way to run out
    of memory. A dropped heartbeat costs nothing — they are retained and repeat."""
    import app.integrations.mqtt_ingest as mi

    class _FullQueue:
        @staticmethod
        def qsize():
            return mi._INGEST_MAX_PENDING + 1

    monkeypatch.setattr(type(mi._INGEST), "_work_queue",
                        property(lambda self: _FullQueue()), raising=False)
    submitted = []
    monkeypatch.setattr(mi._INGEST, "submit",
                        lambda *a, **k: submitted.append(a))

    class _Msg:
        topic = "sandy/node/abc/status"
        payload = b"{}"

    before = mi._stats.get("dropped", 0)
    mi._on_message(None, None, _Msg())

    assert submitted == [], "the queue was full and the message was queued anyway"
    assert mi._stats.get("dropped", 0) == before + 1, "a drop went uncounted"


def test_one_drop_is_one_line(caplog):
    """paho calls the disconnect callback twice for a single event."""
    import logging

    import app.integrations.mqtt_ingest as mi

    mi._stats["last_disconnect_log"] = 0.0
    with caplog.at_level(logging.WARNING, logger="app.integrations.mqtt_ingest"):
        mi._on_disconnect(None, None, None, 141)
        mi._on_disconnect(None, None, None, 141)

    lines = [r for r in caplog.records if "disconnected" in r.getMessage()]
    assert len(lines) == 1, f"one drop produced {len(lines)} log lines"


def test_a_later_drop_is_still_reported(caplog):
    """The de-duplication is a one-second window, not a mute button — a link
    that really drops twice must still look like two drops."""
    import logging

    import app.integrations.mqtt_ingest as mi

    mi._stats["last_disconnect_log"] = 0.0
    with caplog.at_level(logging.WARNING, logger="app.integrations.mqtt_ingest"):
        mi._on_disconnect(None, None, None, 141)
        mi._stats["last_disconnect_log"] = time.time() - 5.0
        mi._on_disconnect(None, None, None, 141)

    lines = [r for r in caplog.records if "disconnected" in r.getMessage()]
    assert len(lines) == 2
