import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from iclaude_runtime import reminders

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)  # a Friday
LONDON = ZoneInfo("Europe/London")
OWNER = "+15551234567"


class Sent:
    def __init__(self):
        self.messages = []

    def send(self, to, text, key, context=None):
        self.messages.append((to, text, key))


def test_parse_when_local_time_and_relative():
    assert reminders.parse_when("2026-10-23T17:00", None, LONDON, NOW) == datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)
    assert reminders.parse_when(None, 30, LONDON, NOW) == NOW + timedelta(minutes=30)
    with pytest.raises(ValueError):
        reminders.parse_when("2026-10-23T10:00", None, LONDON, NOW)
    with pytest.raises(ValueError):
        reminders.parse_when(None, None, LONDON, NOW)


def test_next_due_keeps_wall_clock_across_dst():
    friday = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)  # 08:00 BST
    assert reminders.next_due(friday, "none", LONDON) is None
    monday = reminders.next_due(friday, "weekdays", LONDON)
    assert monday.astimezone(LONDON).strftime("%a %H:%M") == "Mon 08:00"
    assert monday.utcoffset() == timedelta(0) and monday.hour == 8  # GMT after the clocks change
    assert reminders.next_due(friday, "weekly", LONDON).astimezone(LONDON).strftime("%a %d %H:%M") == "Fri 30 08:00"


def test_store_add_list_cancel(tmp_path):
    store = reminders.Store(tmp_path / "r.json")
    item = store.add(OWNER, "  call   mum ", NOW + timedelta(hours=1), "none")
    assert item["text"] == "call mum"
    assert [i["id"] for i in store.list(OWNER)] == [item["id"]]
    assert store.list("+15550000000") == []
    assert not store.cancel(item["id"], "+15550000000")
    assert store.cancel(item["id"], OWNER) and store.list() == []
    with pytest.raises(ValueError):
        store.add(OWNER, "x", NOW, "hourly")


def test_fire_due_sends_once_and_reschedules(tmp_path):
    store, sent = reminders.Store(tmp_path / "r.json"), Sent()
    once = store.add(OWNER, "stretch", NOW - timedelta(minutes=1), "none")
    daily = store.add(OWNER, "pills", NOW - timedelta(minutes=2), "daily")
    store.add(OWNER, "later", NOW + timedelta(hours=1), "none")
    assert store.fire_due(NOW, sent, LONDON) == 2
    assert {m[1] for m in sent.messages} == {"Reminder: stretch", "Reminder: pills"}
    left = {i["id"]: i for i in store.list()}
    assert once["id"] not in left and datetime.fromisoformat(left[daily["id"]]["due"]) > NOW
    assert store.fire_due(NOW, sent, LONDON) == 0


def test_fire_due_skips_stale_one_offs_after_downtime(tmp_path):
    store, sent = reminders.Store(tmp_path / "r.json"), Sent()
    store.add(OWNER, "old", NOW - timedelta(days=2), "none")
    late = store.add(OWNER, "late", NOW - timedelta(hours=1), "none")
    store.fire_due(NOW, sent, LONDON)
    assert [m[1] for m in sent.messages] == ["Reminder: late (was due 12:00)"] and store.list() == []
    assert late


def test_failed_send_keeps_the_reminder(tmp_path):
    store = reminders.Store(tmp_path / "r.json")
    store.add(OWNER, "x", NOW - timedelta(minutes=1), "none")

    class Down:
        def send(self, *a):
            raise OSError("down")

    with pytest.raises(OSError):
        store.fire_due(NOW, Down(), LONDON)
    assert len(store.list()) == 1


def test_tools_act_for_the_person_in_the_conversation(tmp_path):
    env = {"INKBOX_ALLOWED_USERS": f"{OWNER},+15559998888,me@icloud.com"}
    store = reminders.Store(tmp_path / "r.json")
    session = SimpleNamespace(reply_meta={"sender": "+15559998888"})
    tools = reminders.handlers(lambda: env, store, lambda: session)
    result = asyncio.run(tools["remind"]({"text": "dentist", "in_minutes": 60}))
    assert "Scheduled" in result["content"][0]["text"]
    assert store.list()[0]["to"] == "+15559998888"
    session.reply_meta = {"sender": "me@icloud.com"}
    result = asyncio.run(tools["remind"]({"text": "x", "in_minutes": 5}))
    assert result.get("is_error") and "iMessage" in result["content"][0]["text"]
    session.reply_meta = {"sender": "+15550000000"}
    assert asyncio.run(tools["remind"]({"text": "x", "in_minutes": 5})).get("is_error")
    session.reply_meta = {"sender": OWNER}
    assert asyncio.run(tools["list_reminders"]({}))["content"][0]["text"] == "No reminders set."
    other = store.list()[0]["id"]
    assert asyncio.run(tools["cancel_reminder"]({"id": other})).get("is_error")
    assert asyncio.run(tools["remind"]({"text": "x", "at": "2001-01-01T00:00"})).get("is_error")


def test_tool_server_registers_with_the_sdk():
    pytest.importorskip("claude_agent_sdk")
    server, names = reminders.tool_server(lambda: {})
    assert names == ["remind", "list_reminders", "cancel_reminder"]
    assert server["type"] == "sdk" and server["name"] == "iclaude"
