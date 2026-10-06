"""«Reset my data» forgets everything but the account and its subscription.

Every field a `sandy_users` row can hold is named here as kept or forgotten, read
from the code that writes the row; a field nobody classified fails the test, so a
new one is decided on the day it is added, not found in a customer's reset later.
Kept: how they sign in, the subscription, the robot's pairing (its own collections),
the token generation, the push tokens and the usage counters.
"""
import ast
import pathlib

import mongomock

from app import db as appdb
from app.features import account_delete, notify_prefs, push_tokens_store, usage_store, users_store

APP = pathlib.Path(__file__).resolve().parents[1] / "cloud" / "app"
_UPDATE_OPS = {"$set", "$inc", "$unset", "$setOnInsert", "$push", "$addToSet", "$pull"}


def _key(node, consts):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return node.values[0].value
    return None


def _fields_written(path):
    """Top-level fields a module writes to a user row: update operators' keys, the
    inserted `doc`, and keys added to the `sets`/`updates` it builds."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
              and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
              for t in n.targets if isinstance(t, ast.Name)}
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if _key(k, consts) in _UPDATE_OPS:
                    if isinstance(v, ast.Dict):
                        keys += [_key(x, consts) for x in v.keys]
                    elif isinstance(v, ast.DictComp):
                        keys.append(_key(v.key, consts))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(t, ast.Name) and t.id in ("doc", "sets", "updates"):
                    keys += [_key(x, consts) for x in node.value.keys]
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and t.value.id in ("sets", "updates")):
                    keys.append(_key(t.slice, consts))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and t.value.id in ("sets", "updates")):
                    keys.append(_key(t.slice, consts))
    return {k.split(".")[0] for k in keys if k and not k.startswith("$")}


def _user_row_writers():
    """Every module that names the users collection, but the reset itself."""
    return [p for p in APP.rglob("*.py")
            if '"sandy_users"' in p.read_text(encoding="utf-8")
            and p.name != "account_delete.py" and p.name != "tenant_version.py"]


def test_every_user_row_field_is_kept_or_forgotten():
    found = set()
    for path in _user_row_writers():
        found |= _fields_written(path)
    assert {"onboarding", "subscription", "token_gen", "notifications"} <= found, "reader is blind"
    kept, forgotten = account_delete.USER_ROW_KEPT, account_delete.USER_ROW_FORGOTTEN
    assert not kept & forgotten
    unclassified = found - kept - forgotten
    assert not unclassified, (
        f"sandy_users fields nobody decided about on reset: {sorted(unclassified)} — "
        "add each to USER_ROW_KEPT or USER_ROW_FORGOTTEN in account_delete.py")
    stale = (kept | forgotten) - found
    assert not stale, f"classified fields nothing writes any more: {sorted(stale)}"


def _full_account():
    d = mongomock.MongoClient().db
    appdb.configure(d)
    u = users_store.create_email_user("a@b.c", "hash", name="سامي")
    uid = u["_id"]
    users_store.set_onboarding(uid, preferred_name="سمسم", interests=["قهوة"], notes="بيحب الصبح")
    users_store.record_nudge_answer(uid, "q1", "منيح")
    users_store.set_persona(uid, dialect="egyptian", custom_instructions="احكي باختصار")
    users_store.set_budget(uid, 900)
    users_store.set_city(uid, "عمّان")
    users_store.set_timezone(uid, "Asia/Amman")
    users_store.set_subscription(uid, "active", plan="monthly", source="apple")
    users_store.move_token_generation(uid)
    notify_prefs.save(uid, {"daily": False, "quiet_start": "23:00"})
    push_tokens_store.register_token(uid, "tok-1")
    usage_store.add_voice_seconds(uid, 30)
    d.sandy_usage_rl.insert_one({"_id": f"{uid}:1", "user_id": uid, "n": 1})
    return d, uid


def test_a_reset_keeps_the_account_and_forgets_the_person():
    d, uid = _full_account()
    before = d.sandy_users.find_one({"_id": uid})
    assert account_delete.USER_ROW_FORGOTTEN <= set(before)   # the fixture fills every field

    assert account_delete.wipe_account_data(uid)["ok"]

    after = d.sandy_users.find_one({"_id": uid})
    for field in account_delete.USER_ROW_KEPT & set(before):
        assert after.get(field) == before[field], field
    assert after["onboarding"] == users_store.fresh_onboarding()
    for field in account_delete.USER_ROW_FORGOTTEN - {"onboarding"}:
        assert field not in after, field
    assert users_store.is_subscriber(uid)
    assert users_store.token_generation(uid) == 1
    # Notifications keep going and today's allowance is not handed out again.
    assert push_tokens_store.tokens_for_user(uid) == ["tok-1"]
    assert usage_store.voice_seconds_today(uid) == 30
    assert d.sandy_usage_rl.count_documents({"user_id": uid}) == 1
    appdb.reset()


def test_a_reset_keeps_the_robot_paired(monkeypatch):
    """«صفّر بياناتي» is for starting over, not for losing the robot: the board stays
    the account's, its parts stay in Control, and its own key stays valid."""
    from app.api.auth_handlers import make_token
    from app.api.server import create_app
    from app.features import device_store, node_store
    from app.utils.user_profiles import active_user_profile_context

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    d = mongomock.MongoClient().db
    c = create_app(mongo_db=d).test_client()
    appdb.configure(d)
    with active_user_profile_context({"chat_id": "u1"}):
        paired = node_store.pair_node("ABCD1234", label="ساندي")
        assert paired["ok"]
        node_id = paired["node_id"]
        assert device_store.add_device(
            "neck", "الرقبة", "dimmer",
            {"kind": "node", "node_id": node_id, "output": "servo"})["ok"]
    keys_before = list(d.sandy_device_keys.find({}))
    assert keys_before, "pairing opens the board's key enrolment"

    auth = {"Authorization": f"Bearer {make_token('user', user_id='u1')}"}
    r = c.post("/api/account/reset", json={"confirm": "RESET"}, headers=auth)
    assert r.status_code == 200 and r.get_json()["ok"]

    assert node_store.get_node_any_tenant(node_id)["user_id"] == "u1"
    assert list(d.sandy_device_keys.find({})) == keys_before
    with active_user_profile_context({"chat_id": "u1"}):
        assert [n["node_id"] for n in node_store.list_nodes()] == [node_id]
        assert [x["name"] for x in device_store.list_devices()] == ["neck"]
        # Pairing it again is still "already ours", not "someone else's".
        assert node_store.pair_node("ABCD1234")["already"] is True
    r = c.get("/api/account", headers=auth)
    assert [n["node_id"] for n in r.get_json()["nodes"]] == [node_id]
    appdb.reset()
