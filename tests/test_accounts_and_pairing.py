"""Turning one hard-coded owner into real accounts.

Everything here existed and worked — for exactly one person. The shape of the
system said "owner" everywhere: a password in an environment variable, an
account minted from it, and voice sessions that resolved that account no matter
who was on the line. None of it was a bug at one user and none of it survived
two.

The tests below are the boundaries that make a second customer safe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_the_shared_owner_password_is_gone():
    """One password, one account, everybody who typed it.

    `POST /api/auth` logged anyone holding a single shared password into an
    account called "owner" — the same journal, the same expenses, the same
    voiceprint. It also could not be deleted or recovered, so every question
    about selling a robot dead-ended there.
    """
    server = _read("cloud/app/api/server.py")
    assert 'route("/api/auth", methods=["POST"])' not in server
    # Checking for the bare name matched the comment explaining the removal —
    # a test that fails on its own documentation. What matters is that the
    # function is neither imported nor called, so look for those two shapes.
    assert "        check_owner_password,\n" not in server, "import left behind"
    assert "check_owner_password(" not in server, "the password check is back"

    auth = _read("ios/SandyApp/Core/Networking/APIClient+Auth.swift")
    assert "func devLogin" not in auth
    view = _read("ios/SandyApp/Core/Auth/AuthView.swift")
    assert "devLogin()" not in view and "auth.ownerPassword" not in view


def test_a_voice_session_belongs_to_whoever_is_on_it():
    """The worst of the set, because it leaked rather than failed.

    Voice memory called `get_or_create_owner()` — one account, from an
    environment variable, for every session on the server. With one user it was
    invisible. With two, the second customer is handed the first one's diary.
    """
    mem = _read("cloud/app/api/voice_ws/memory.py")
    assert "def set_voice_identity" in mem
    assert "get_voice_identity()" in mem, (
        "the session identity is ignored again and every caller resolves to the "
        "same global owner")

    # **Not thread-local.** It was, and the identity vanished the moment any
    # work moved to a pool thread — which is where nearly all of it happens.
    # The log said it in two consecutive lines: `auth OK owner=1f69b997…`
    # followed immediately by `unidentified session`.
    #
    # A plain module global would be worse still: two calls at once would
    # overwrite each other and one caller would answer as the other.
    assert "threading.local()" not in mem, (
        "session identity is back in thread-local storage; anything running in "
        "an executor will not see it")
    assert "contextvars.ContextVar" in mem
    # **One variable, one setter.** An earlier attempt at this had two — the
    # session's identity and a separate "override" for pool threads — which is
    # one fact stored in two places, and two places drift.
    assert "bind_identity" not in mem, (
        "a second identity mechanism is back; one fact, one home")
    # Two facts, plus anything **derived** from them and cleared with them.
    # `_speaker_name` is the display name for `_identity`, memoised because
    # `_speaker_directive` runs on the audio event loop once per utterance and a
    # find_one there is an audible pause. `set_voice_identity` resets it in the
    # same call that sets the identity, so it cannot outlive or contradict it —
    # which is the drift this assertion exists to prevent.
    assert mem.count("ContextVar(") <= 3, (
        "a third *independent* fact about the session appeared; identity and "
        "channel are the only two, and anything else must be derived from them")
    assert '_speaker_name.set("")' in mem, (
        "the derived name is not cleared where the identity is set — that is "
        "exactly how two copies of one fact drift")

    session = _read("cloud/app/api/voice_ws/session.py")
    for call in ("_build_system_instruction, _who",
                 "get_voice_identity(), get_voice_channel()",
                 "_verify_owner, recent.snapshot(), get_voice_identity()"):
        assert call in session, (
            f"`{call}` stopped carrying the identity — that work runs on a pool "
            "thread and will resolve to nobody")

    session = _read("cloud/app/api/voice_ws/session.py")
    assert 'claims.get("role") in ("owner", "user")' in session, (
        "voice is owner-only again — every Apple/Google customer is locked out "
        "of the feature the product is named for")
    assert "get_node_any_tenant(device_id)" in session, (
        "the robot no longer resolves its own owner, so it speaks as whatever "
        "account the environment happens to name")


def test_an_unidentified_voice_session_gets_no_memory_at_all():
    """The leak, reproduced in one sentence.

    The robot identifies itself with a device name (`sandy-brain-s3`), not its
    node id, so "who owns this node?" returned nothing — and the code fell back
    to `get_or_create_owner()`, the pre-accounts owner. A brand-new account
    signed in, asked her something out loud, **and she greeted him by the
    previous owner's name and read out his old tasks.**

    In a product with two customers that same line hands one person the other's
    journal.

    The fallback was answering the wrong question. Not "who is this most
    likely?" but "who is this for certain?" — and when the answer is unknown it
    must be **nobody**. A robot with no memory is a small bug. A robot with
    somebody else's memory is a breach.
    """
    mem = _read("cloud/app/api/voice_ws/memory.py")
    # Look for the CALL, not the name: the comment explaining why the fallback
    # was removed mentions it, and a test that fails on its own documentation
    # teaches people to delete the documentation.
    assert "uid = users_store.get_or_create_owner()" not in mem, (
        "the owner fallback is back — an unidentified session will be handed "
        "the legacy owner's entire history")
    assert "return OWNER_CHAT_ID" not in mem, "the env-var identity fallback is back"
    assert 'unidentified session — starting with no memory' in mem, (
        "the empty case is silent again; it must be visible in the log")


def test_the_board_identifies_itself_by_its_node():
    """The other half: the lookup could never have succeeded.

    `SANDY_DEVICE_ID` was a model name. The voice handshake feeds it straight
    into a node lookup, so it was guaranteed to miss — which is what made the
    fallback fire on every single session rather than rarely.
    """
    # `secrets.h` holds live credentials and is gitignored, so it does not exist
    # on CI. Asserting against it made this pass locally and fail on the server
    # — a test that only runs on one machine is not a test.
    #
    # The rule is asserted where it can always be read: the committed example,
    # which is also the file the next person copies. The real one is checked too
    # when it happens to be present.
    example = _read("firmware/brain-core/main/secrets.example.h")
    assert "SANDY_DEVICE_ID" in example and "SANDY_PAIR_CODE" in example
    assert "معرّف الوحدة" in example or "node id" in example.lower(), (
        "the example no longer tells the next person that the device id must be "
        "the node id — which is the mistake that leaked one owner's memory to "
        "another")

    real = _ROOT / "firmware/brain-core/main/secrets.h"
    if real.exists():
        sec = real.read_text(encoding="utf-8")
        assert '#define SANDY_DEVICE_ID     "8421"' in sec, (
            "this board announces a model name again; the owner lookup cannot "
            "resolve it and its voice sessions become anonymous")
        assert '#define SANDY_PAIR_CODE     "8421"' in sec, (
            "the brain and the camera are on different node ids again — they "
            "are one robot and must share one id")


def test_a_robot_can_only_be_claimed_once():
    """The check was scoped to the caller, which is not a check.

    `pair_node` asked "have *I* paired this code before?" — so two accounts
    could each claim the same robot and both listen to it. With a four-character
    code that is ten thousand guesses, and the rate limit is what makes sweeping
    them impractical.
    """
    store = _read("cloud/app/features/node_store.py")
    assert "already_claimed" in store
    assert 'get_db()[_COLL].find_one({"node_id": node_id})' in store, (
        "the claim check is tenant-scoped again — it cannot see a robot another "
        "account already owns, which is the only case that matters")

    api = _read("cloud/app/api/devices_api.py")
    assert 'scope="node_pair"' in api, "pairing is unthrottled"


def test_the_first_owner_is_not_locked_out_of_his_own_robot():
    """Claim-once nearly cost the first customer his hardware.

    Everything he owned sat under an account called "owner", reachable only
    through the shared password — which the same change deleted. So his robot
    was claimed by an account that can no longer be signed into, and claim-once
    would answer "this belongs to someone else" forever. He would have lost his
    robot to an upgrade.

    The exception is exactly one account wide: the pre-accounts owner, which has
    no login path left. Every real account stays protected.
    """
    store = _read("cloud/app/features/node_store.py")
    assert "_is_legacy_owner" in store
    assert '== "owner"' in store, (
        "the takeover no longer checks the provider — widen this and anyone can "
        "claim a robot that already has an owner")
    assert "not _is_legacy_owner(claimed.get(\"user_id\"))" in store


def test_selling_a_robot_wipes_it_before_releasing_it():
    """Order is the whole thing.

    The publish path checks that the caller owns the node. Unpair first and the
    board becomes unreachable by the only person entitled to erase it — so it
    ships to its buyer still holding the seller's Wi-Fi name and password.
    """
    api = _read("cloud/app/api/devices_api.py")
    i_wipe = api.index("factory_reset")
    i_unpair = api.index("r = unpair_node(node_id)")
    assert i_wipe < i_unpair, (
        "the robot is released before it is wiped, so the wipe cannot be "
        "delivered and the buyer inherits the seller's home network")
    assert "board_wiped" in api, (
        "the caller cannot tell a wiped board from an offline one — those need "
        "different actions before a sale")

    fw = _read("firmware/brain-core/main/sandy_wifi.c")
    assert "nvs_erase_all" in fw, (
        "the board erases named keys instead of everything; anything stored "
        "later and forgotten here ships to the next owner")


def test_account_deletion_exists_and_frees_the_hardware():
    """Required by Apple since 2022, and right regardless.

    Unpairing first is not politeness: a node claimed by a deleted account stays
    claimed forever, and the hardware becomes permanently unpairable by anyone,
    including the person holding it.
    """
    api = _read("cloud/app/api/account_api.py")
    assert 'methods=["DELETE"]' in api
    assert '!= "DELETE"' in api, "no confirmation on the one call with no undo"
    i_unpair = api.index("unpair_node")
    i_delete = api.index("delete_account(uid)")
    assert i_unpair < i_delete, "robots are stranded when the account goes"

    from app.features.account_delete import _BY_USER, _STM
    assert len(_BY_USER) >= 20, (
        "collections were dropped from the deletion list — a delete that misses "
        "one reports success while keeping the diary")
    assert _STM == "sandy_stm"


def test_the_board_can_hold_its_own_broker_key():
    """Boards used to ship with one broker login compiled into all of them.

    That was the largest hole in the product: one customer's credentials worked
    on every other customer's topics, and a single extracted board exposed the
    fleet with no way to rotate one key.

    The board could already *read* a stored credential — but nothing anywhere
    ever wrote one, so the mechanism existed and was permanently empty. A read
    path with no writer is not half a fix; it looks like a fix and is not one.
    Both halves are asserted here for that reason.
    """
    fw = _read("firmware/brain-core/main/sandy_mqtt.c")
    assert 'CREDS_NS "sandy_mqtt"' in fw
    assert "nvs_open(CREDS_NS, NVS_READONLY" in fw, "the read half is gone"
    assert "nvs_set_str(h, \"user\", user)" in fw, (
        "nothing writes a credential — the board can never take its own key")
    assert ".username   = s_user" in fw, (
        "the compiled-in credentials are wired straight into the client again")


def test_each_board_gets_its_own_client_id():
    """A broker allows one connection per client id, and drops the older one.

    Every brain used to connect as the same fixed name, so two robots on the
    same broker kicked each other off in a loop that never settles. Per-device
    credentials do not help: the collision is on the id, not the login. The
    camera and the room node already derive theirs from the chip's own id.
    """
    fw = _read("firmware/brain-core/main/sandy_mqtt.c")
    assert '"sandy-brain-%s", s_node_id' in fw, (
        "the client id is fixed again — two robots will fight over it")

    for path, prefix in (("vision-core/cam_mqtt.ino", "sandy-cam-"),
                         ("room-node/room-node.ino", "sandy-room-")):
        src = _read(path)
        assert prefix in src and "getEfuseMac()" in src, (
            f"{path} no longer derives a unique client id")


def test_the_server_hands_a_board_its_own_broker_key():
    """The credential travels on the voice handshake, deliberately.

    Sending it over the broker would mean the shared login must keep working
    for ever — the exact thing being retired. The voice socket authenticates
    against a different key, so it still works after the shared broker login is
    revoked, which is what makes revoking it possible at all.

    A board with no row configured must get nothing and keep running on what it
    has: a missing config var may not take a working fleet off the air.
    """
    from app import config
    from app.features import broker_creds

    original = config.SANDY_BROKER_CREDS
    broker_creds.reset_cache()
    config.SANDY_BROKER_CREDS = json.dumps({
        "sandy0001": {"user": "node-0001", "pass": "s3cret"},
        "sandy0002": {"user": "node-0002"},          # half a credential
    })
    try:
        assert broker_creds.creds_for_device("sandy0001") == {
            "user": "node-0001", "pass": "s3cret"}
        assert broker_creds.creds_for_device("sandy0002") is None, (
            "half a credential was handed out — the board would store it and "
            "then fail to connect with no fallback left")
        assert broker_creds.creds_for_device("sandy9999") is None

        broker_creds.reset_cache()
        config.SANDY_BROKER_CREDS = "{not json"
        assert broker_creds.creds_for_device("sandy0001") is None, (
            "a malformed config must not raise into the handshake")
    finally:
        config.SANDY_BROKER_CREDS = original
        broker_creds.reset_cache()

    session = _read("cloud/app/api/voice_ws/session.py")
    assert "creds_for_device" in session, "the handshake hands out nothing"
    i_auth = session.index('reply: Dict[str, Any] = {"type": "auth_ok"}')
    i_send = session.index("ws.send(json.dumps(reply))")
    assert i_auth < session.index("creds_for_device") < i_send

    fw = _read("firmware/brain-core/main/sandy_voice.c")
    assert "mqtt_sandy_set_credentials" in fw, (
        "the board is told its key and does nothing with it")
