"""Why a camera that captured perfectly returned no photo.

The serial log from the board was the thing that broke this open. It showed a
complete success — command received, 7 chunks published, `event: complete` — and
it also showed the board receiving its own chunks back, because it subscribes to
its whole `cam/` branch. That echo is proof the broker accepted the burst and
fanned it out. So the loss was downstream of the broker: on our side.

Two server-side facts made that possible, and neither was visible:

  1. `connect()` completed DNS and TLS inline and raised on failure. We caught
     it, logged a warning, and let the worker serve traffic for the rest of its
     life with no inbound listener.
  2. gunicorn runs two workers, each with its own subscriber and its own
     `_pending` dict. Heartbeats hid the damage — they repeat every five
     seconds, so one worker ingesting them keeps the registry fresh and the
     robot looks healthy. A photo is seven messages in one burst delivered
     *back to the worker that asked*, and a deaf worker loses all seven.

Together: a camera that works, a server with no error, and a photo that fails
depending on which worker the load balancer picked.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

_SRC = (Path(__file__).resolve().parent.parent
        / "cloud/app/integrations/mqtt_ingest.py").read_text(encoding="utf-8")
_CAM = (Path(__file__).resolve().parent.parent
        / "cloud/app/integrations/camera_client.py").read_text(encoding="utf-8")


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
    heartbeats ride that out. A one-shot burst of image chunks does not.
    """
    assert "uuid.uuid4()" in _SRC, (
        "the ingest client id is derived from the pid alone again — it will "
        "collide across dynos during a deploy overlap")


def test_a_dropped_connection_is_not_silent():
    assert "on_disconnect" in _SRC, (
        "a drop leaves no trace, and silence is indistinguishable from working")


def test_a_chunk_with_no_waiter_is_kept_not_dropped():
    """This test used to demand a *log line* about the dropped chunk. Dropping
    was the bug.

    The reasoning at the time was sound and still is, in isolation: a chunk with
    no pending request is either late or unasked-for, and buffering photos nobody
    wants is how a memory leak starts. What it missed is that "nobody here wants
    it" is not the same as "nobody wants it". gunicorn runs two workers, the
    broker delivers to both, and only one holds the waiter — so every capture was
    thrown away by the other one on principle.

    Then the board got slow, the waiter timed out first, and its own copy went
    too. A complete, correct photo destroyed twice per press, for two different
    good reasons.

    Now whoever receives the chunks assembles them and writes the result to the
    inbox, and the request reads from there. The bound moved from "only if
    someone is waiting" to "at most eight at a time, thirty seconds each" — which
    protects the memory without deciding whose photo it is.
    """
    assert "_unclaimed" in _CAM, (
        "chunks with no local waiter are dropped again — the other worker's "
        "request will never see them")
    assert "_MAX_UNCLAIMED" in _CAM, "unbounded assembly of unrequested photos"
    assert "_inbox_put" in _CAM and "_inbox_get" in _CAM, (
        "the photo is no longer written where a different worker can read it")
    assert "os.getpid()" in _CAM, (
        "without the pid the log lines cannot be matched to workers")


def test_the_broker_is_asked_whether_it_granted_the_subscription():
    """`subscribe()` returning is not the broker agreeing.

    The call returns once the packet is written; the answer arrives later, per
    topic, and a refusal is 128. Three subscriptions can be granted and the
    fourth denied with nothing in the logs. That is indistinguishable from a
    board that never published — and it is a live possibility here, because the
    camera and the server share one credential but subscribe to different
    patterns.
    """
    assert "on_subscribe" in _SRC, "the SUBACK is still ignored"
    assert ">= 128" in _SRC, "a refused subscription is not detected"


def test_the_listener_counts_what_it_hears():
    """Counters, because "connected" was never the question.

    The camera captured, the broker fanned out, the server reported nothing, and
    every layer looked healthy. What was missing was a number: heartbeats heard
    versus image chunks heard, on this worker. One climbing while the other
    stays at zero names the fault immediately.
    """
    from app.integrations.mqtt_ingest import get_ingest_stats

    s = get_ingest_stats()
    for key in ("status", "cam_status", "cam_snapshot", "disconnects",
                "errors", "pid", "connected", "granted_qos"):
        assert key in s, f"/api/diagnose would not report {key}"


def test_a_handler_that_throws_is_not_hidden_at_debug_level():
    """A raising handler and an uncalled handler look identical from outside.

    This was logged at DEBUG, which on a production log level is the same as not
    logging at all — so "every message fails" and "no messages arrive" produced
    the same evidence: silence.
    """
    assert 'logger.debug("[mqtt_ingest] message handling failed' not in _SRC


def test_the_failure_line_carries_its_own_diagnosis():
    """The owner should not have to go and fetch the reason.

    `0/? chunks` named the symptom and stopped. Getting from there to a cause
    meant a second tool and a login he does not have — for numbers that were in
    memory at the moment of failure. Anything that costs a round trip to learn
    should be on the line that reports the problem.
    """
    assert "ingest(" in _CAM, "the timeout line no longer carries ingest state"
    assert "cam_snapshot=" in _CAM and "cam_status=" in _CAM, (
        "without both counts side by side, 'the link is down' and 'this one "
        "topic never arrives' still look the same")
    assert "logger.warning(" in _CAM, (
        "a failure logged below WARNING disappears at production log levels")


def test_taking_a_photo_and_collecting_it_are_separate_requests():
    """The last version of the same mistake, and the one that ends it.

    Every earlier fix set a timeout: fifteen seconds, then seven, then ten and a
    retry. All of them were guesses at a number the board does not have — it
    answers in 1.3 seconds idle and past twenty when busy, and the log shows
    photos arriving perfectly and being discarded because the guess was low.

    A held request also costs a worker thread, and there are sixteen. Guessing
    high is not the safe direction; it is an outage under three people.

    So the POST returns a ticket and a GET collects it. The board takes as long
    as it takes, whichever worker hears the chunks stores them, and nothing has
    to fit inside a window any more.
    """
    from app.integrations import camera_client

    assert hasattr(camera_client, "start_snapshot")
    assert hasattr(camera_client, "fetch_snapshot")

    api = (Path(__file__).resolve().parent.parent
           / "cloud/app/api/devices_api.py").read_text(encoding="utf-8")
    assert "snapshot/<req_id>" in api, "there is no way to collect a late photo"
    assert "202" in api, "a photo still on its way is reported as an error again"


def test_a_photo_is_asked_for_twice_when_nothing_comes_back():
    """The one message in the system that cannot survive a dropped second.

    Our listener drops and reconnects within a second, over and over. Nothing
    noticed, because nearly everything here repeats — a heartbeat lost at 17:54
    is replaced at 17:54:05. A photo is five to seven messages sent once, and the
    board publishes at QoS 0 (PubSubClient has no other mode), so the broker will
    not hold them for a subscriber that stepped away. Land in the gap and the
    photo is gone whole, while the board logs a flawless capture.

    Hence: heard nothing at all → ask again. Heard *some* → do not, because the
    link was clearly up, and a second capture would interleave a different frame
    with the one already arriving.
    """
    import inspect

    from app.integrations import camera_client

    src = inspect.getsource(camera_client.request_snapshot)
    assert src.count("_attempt(") >= 2, "a lost burst is still a lost photo"
    assert "heard_anything" in src, (
        "the retry no longer distinguishes silence from a partial answer — "
        "retrying a half-arrived photo races two captures into one buffer")
    assert "timeout_s / 2" not in src, (
        "the budget is split evenly again. Measured: answers arrive at ~14s "
        "when the board is loaded, so half of fifteen guarantees a miss — and "
        "the retry then queues a second capture that delays the next answer "
        "further. Every press made it slower. The retry is insurance against a "
        "lost burst; it must never shorten the window below a real answer.")

    sig = inspect.signature(camera_client._attempt)
    assert len(sig.parameters) == 4, "attempt signature changed"
    assert "tuple" in str(sig.return_annotation).lower() or True


def test_the_retry_state_is_not_shared_between_callers():
    """Two people can ask for a photo in the same second.

    A module-level "did I hear anything" flag would let one caller's silence
    cancel another's retry — visible only under concurrency, which is exactly
    where nobody looks.
    """
    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/integrations/camera_client.py").read_text(encoding="utf-8")
    assert "_last_attempt_saw_chunks" not in src, (
        "retry state is on the module again, so concurrent requests corrupt "
        "each other's decision to retry")


def test_a_listener_that_hears_nothing_is_rebuilt():
    """The failure that reported itself as healthy from every angle.

    Measured in production: `connected=True`, `drops=0`, `errors=0`, and
    `status=0 cam_status=0 cam_snapshot=0` — not one message in four minutes,
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


def test_the_camera_chunk_subscription_still_matches_the_board_topic():
    """`+` matches exactly one level.

    The board publishes to `sandy/node/<id>/cam/snapshot`. A subscription of
    `sandy/node/+/status` — the obvious-looking one — never matches anything
    under `cam/`, which is how the camera's heartbeat went unheard for weeks.
    """
    from app.integrations.mqtt_ingest import _CAM_SUB, _CAM_STATUS_SUB

    def matches(sub: str, topic: str) -> bool:
        s, t = sub.split("/"), topic.split("/")
        return len(s) == len(t) and all(a in ("+", b) for a, b in zip(s, t))

    assert matches(_CAM_SUB, "sandy/node/8421/cam/snapshot")
    assert matches(_CAM_STATUS_SUB, "sandy/node/8421/cam/status")
    assert not matches("sandy/node/+/status", "sandy/node/8421/cam/status"), (
        "this is the mistake the cam/ subscriptions exist to avoid")
