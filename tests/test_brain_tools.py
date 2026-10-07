"""Each brain tool against the blocks (no model involved)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from brain_fakes import A, brain_db, on_node  # noqa: F401 — fixture

from app.blocks import entries, items, schedules
from app.blocks.kinds import LIST, LOG, SCHEDULE, names
from app.brain import tools
from app.brain.ctx import TurnCtx
from app.utils.time import USER_TZ
from app.utils.user_profiles import active_user_profile_context


def _run(name, **args):
    return tools.execute(name, args, TurnCtx(user_id="userA", message="x"))


def _future(days=1, hour=17):
    return (datetime.now(USER_TZ) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


@pytest.fixture
def tenant_a(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        yield brain_db


def test_sixteen_tools_and_every_one_has_a_handler():
    specs = tools.openai_tools()
    assert len(specs) == 16
    assert {s["function"]["name"] for s in specs} == set(tools.HANDLERS)


def test_enums_come_from_the_kinds_table():
    by_name = {d["name"]: d for d in tools.declarations()}
    assert by_name["remember"]["parameters"]["properties"]["kind"]["enum"] == list(names(LOG))
    assert by_name["schedule"]["parameters"]["properties"]["kind"]["enum"] == list(names(SCHEDULE))
    list_enum = by_name["list_add"]["parameters"]["properties"]["list"]["enum"]
    assert set(list_enum) == {n for n in names(LIST) if not n.endswith(":")} | {"project"}


def test_voice_declarations_carry_no_empty_objects():
    for d in tools.declarations():
        for spec in d["parameters"]["properties"].values():
            assert not (spec.get("type") == "object" and not spec.get("properties"))


def test_remember_writes_an_entry(tenant_a):
    out = _run("remember", kind="expense", text="قهوة", data={"amount": 3.5})
    assert out["ok"]
    row = entries.get(out["id"])
    assert row["kind"] == "expense" and row["data"] == {"amount": 3.5}
    assert row["source"] == "chat"


def test_remember_refuses_a_kind_or_field_the_table_does_not_have(tenant_a):
    assert _run("remember", kind="gift", text="x")["ok"] is False
    assert _run("remember", kind="expense", text="x", data={"mood": "sad"})["ok"] is False
    assert entries.list_entries() == []


def test_recall_searches_entries_items_and_schedules(tenant_a):
    entries.add("journal", "رحت عالجيم الصبح")
    items.add("tasks", "اشتري حذاء جيم")
    items.add("shopping", "حليب")
    _run("schedule", kind="reminder", text="جيم المسا", when=_future())
    out = _run("recall", query="جيم")
    texts = {r["text"] for r in out["rows"]}
    assert texts == {"رحت عالجيم الصبح", "اشتري حذاء جيم", "جيم المسا"}
    assert all("embedding" not in r and "user_id" not in r for r in out["rows"])


def test_recall_filters_by_kind_list_and_dates(tenant_a):
    old = datetime.now(USER_TZ) - timedelta(days=10)
    entries.add("expense", "قديم", at=old)
    entries.add("expense", "جديد")
    items.add("shopping", "خبز")
    assert [r["text"] for r in _run("recall", kind="expense")["rows"]] == ["جديد", "قديم"]
    since = (datetime.now(USER_TZ) - timedelta(days=2)).date().isoformat()
    assert [r["text"] for r in _run("recall", kind="expense", since=since)["rows"]] == ["جديد"]
    assert [r["text"] for r in _run("recall", list="shopping")["rows"]] == ["خبز"]


def test_list_add_and_project_lists(tenant_a):
    out = _run("list_add", list="tasks", text="ادرس", due=_future(), priority="high")
    item = items.get(out["id"])
    assert item["list"] == "tasks" and item["priority"] == "high" and item["due"]
    out = _run("list_add", list="project", project="بيت", text="دهان")
    assert items.get(out["id"])["list"] == "project:بيت"
    assert _run("list_add", list="gifts", text="x")["ok"] is False


def test_list_update_by_match_text(tenant_a):
    iid = items.add("tasks", "روح عالجيم")
    items.add("tasks", "اقرا كتاب")
    out = _run("list_update", match_text="الجيم", done=True)
    assert out["ok"] and items.get(iid)["done"] is True
    assert _run("list_update", match_text="سباحة", done=True)["error"] == "not found"


def test_list_update_ambiguous_names_the_candidates(tenant_a):
    items.add("tasks", "جيم الصبح")
    items.add("tasks", "جيم المسا")
    out = _run("list_update", match_text="جيم", done=True)
    assert out["ok"] is False and out["error"] == "ambiguous"
    assert len(out["candidates"]) == 2


def test_delete_and_bulk_need_confirmation_and_change_nothing(tenant_a):
    a = items.add("tasks", "جيم الصبح")
    b = items.add("tasks", "جيم المسا")
    out = _run("list_update", match_text="جيم الصبح", delete=True)
    assert out["needs_confirmation"] and "جيم الصبح" in out["summary"]
    out = _run("list_update", match_text="جيم", all_matching=True, done=True)
    assert out["needs_confirmation"]
    assert items.get(a) and items.get(b) and not items.get(a)["done"]


def test_confirmed_delete_runs(tenant_a):
    iid = items.add("tasks", "جيم")
    ctx = TurnCtx(user_id="userA", confirmed=True)
    assert tools.execute("list_update", {"id": iid, "delete": True}, ctx)["ok"]
    assert items.get(iid) is None


def test_schedule_parses_iso_and_words(tenant_a):
    out = _run("schedule", kind="reminder", text="دوا", when=_future(), recurrence="daily")
    row = schedules.get(out["id"])
    assert row["kind"] == "reminder" and row["recurrence"] == "FREQ=DAILY"
    assert row["status"] == "pending"
    out = _run("schedule", kind="reminder", text="اتصل بأمي", when="بكرا")
    tomorrow = (datetime.now(USER_TZ) + timedelta(days=1)).date()
    assert out["when"].startswith(tomorrow.isoformat())


def test_schedule_refuses_an_unreadable_time(tenant_a):
    out = _run("schedule", kind="reminder", text="x", when="لما يصير الجو حلو")
    assert out["ok"] is False
    assert schedules.list_schedules() == []


def test_schedule_update_moves_and_cancel_needs_yes(tenant_a):
    sid = _run("schedule", kind="reminder", text="دكتور", when=_future())["id"]
    later = _future(days=3, hour=10)
    assert _run("schedule_update", match_text="دكتور", when=later)["ok"]
    assert _run("schedule_update", match_text="دكتور", cancel=True)["needs_confirmation"]
    assert schedules.get(sid)["status"] == "pending"
    ctx = TurnCtx(user_id="userA", confirmed=True)
    assert tools.execute("schedule_update", {"id": sid, "cancel": True}, ctx)["ok"]
    assert schedules.get(sid)["status"] == "cancelled"


def test_summarize_reads_only_the_period(tenant_a):
    entries.add("expense", "اليوم")
    entries.add("expense", "زمان", at=datetime.now(USER_TZ) - timedelta(days=40))
    items.add("tasks", "مهمة اليوم")
    out = _run("summarize", period="week")
    texts = {r["text"] for r in out["rows"]}
    assert "اليوم" in texts and "مهمة اليوم" in texts and "زمان" not in texts
    assert _run("summarize", period="week", focus="tasks")["count"] == 1
    assert _run("summarize", period="decade")["ok"] is False


def test_device_control_calls_the_same_handler_and_gate(tenant_a, monkeypatch):
    from app.features import device_store
    sent = {}

    class _Client:
        def send_to_topic(self, topic, payload):
            sent["topic"], sent["payload"] = topic, payload
            return True

    monkeypatch.setattr("app.integrations.room_device.get_room_device_client", lambda: _Client())
    device_store.add_device("living_light", "ضوء الصالة", "switch", on_node("room/light"))
    out = _run("device_control", device="living_light", action="on")
    assert out["ok"] and sent == {"topic": "sandy/node/n1/room/light", "payload": "on"}
    out = _run("device_control", device="غسالة", action="on")
    assert out["ok"] is False and "ضوء الصالة" in out["reply"]


def test_world_tools_reach_their_providers(tenant_a, monkeypatch):
    seen = []
    monkeypatch.setattr("app.features.research.web_answer",
                        lambda q, msg, complete: seen.append(("web", q)) or "📌 الملخص:\nخبر")
    monkeypatch.setattr("app.features.weather.get_weather",
                        lambda city: seen.append(("weather", city)) or dict(
                            city=city, description="مشمس", temp_c=20, feels_like_c=19,
                            max_temp_c=24, min_temp_c=12, humidity=40, sunset="18:10"))
    monkeypatch.setattr("app.features.vision.generate_image_with_azure",
                        lambda prompt: seen.append(("image", prompt)) or b"png")
    ctx = TurnCtx(user_id="userA", message="x")
    assert tools.execute("web_search", {"query": "أخبار"}, ctx)["reply"].startswith("📌")
    assert tools.execute("weather", {"city": "عمّان"}, ctx)["ok"]
    assert tools.execute("image", {"prompt": "قطة"}, ctx)["ok"]
    assert ctx.artifacts["image_bytes"] == b"png" and ctx.artifacts["caption"] == "قطة"
    assert seen == [("web", "أخبار"), ("weather", "عمّان"), ("image", "قطة")]


def test_a_failed_image_or_weather_is_a_refusal_not_a_success(tenant_a, monkeypatch):
    monkeypatch.setattr("app.features.weather.get_weather", lambda city: None)
    monkeypatch.setattr("app.features.vision.generate_image_with_azure", lambda prompt: None)
    ctx = TurnCtx(user_id="userA", message="x")
    assert tools.execute("weather", {"city": "عمّان"}, ctx)["ok"] is False
    assert tools.execute("image", {"prompt": "قطة"}, ctx)["ok"] is False
    assert "image_bytes" not in ctx.artifacts


def test_a_raising_tool_is_a_result_not_a_crash(tenant_a, monkeypatch):
    monkeypatch.setitem(tools.HANDLERS, "recall", lambda a, c: 1 / 0)
    out = _run("recall", query="x")
    assert out["ok"] is False and out["broke"] is True
    assert _run("nope")["ok"] is False
