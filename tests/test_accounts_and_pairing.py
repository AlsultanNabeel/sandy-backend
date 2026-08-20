"""Turning one hard-coded owner into real accounts.

Everything here existed and worked — for exactly one person. The shape of the
system said "owner" everywhere: a password in an environment variable, an
account minted from it, and voice sessions that resolved that account no matter
who was on the line. None of it was a bug at one user and none of it survived
two.

The tests below are the boundaries that make a second customer safe.
"""
from __future__ import annotations

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
    assert "ident = get_voice_identity()" in mem, (
        "the session identity is ignored again and every caller resolves to the "
        "same global owner")

    session = _read("cloud/app/api/voice_ws/session.py")
    assert 'claims.get("role") in ("owner", "user")' in session, (
        "voice is owner-only again — every Apple/Google customer is locked out "
        "of the feature the product is named for")
    assert "get_node_any_tenant(device_id)" in session, (
        "the robot no longer resolves its own owner, so it speaks as whatever "
        "account the environment happens to name")


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
    """Every board still ships with the same broker login compiled in.

    That is the largest remaining hole: one customer's credentials work on every
    other customer's topics, and a single extracted board exposes the fleet with
    no way to rotate one key.

    Issuing per-device credentials needs the broker's own API. Reading them from
    storage is the half that can be built here, and without it the other half
    would require reflashing every robot in the field.
    """
    fw = _read("firmware/brain-core/main/sandy_mqtt.c")
    assert 'nvs_open("sandy_mqtt"' in fw
    assert ".username   = s_user" in fw, (
        "the compiled-in credentials are wired straight into the client again")
