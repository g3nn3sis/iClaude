from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from iclaude_runtime import caldav, reminders, scheduler, watchers

NOW = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)
TZ = ZoneInfo("Europe/London")
ENV = {"INKBOX_ALLOWED_USERS": "+15551234567", "TZ": "Europe/London"}


class Sent:
    def __init__(self):
        self.messages = []

    def send(self, to, text, key, context=None):
        self.messages.append((to, text, key))


def agent(tmp_path, env=None, monkeypatch=None):
    a = scheduler.Agent({**ENV, **(env or {})}, state_path=tmp_path / "state.json")
    a.notifier = Sent()
    a.store = reminders.Store(tmp_path / "r.json")
    return a


def test_settings_parsing():
    assert scheduler.usage_threshold({}) == 80
    assert scheduler.usage_threshold({"ICLAUDE_USAGE_WARN": "off"}) is None
    assert scheduler.usage_threshold({"ICLAUDE_USAGE_WARN": "150"}) == 99
    assert scheduler.briefing_time({"ICLAUDE_BRIEFING_AT": "07:30"}) == time(7, 30)
    assert scheduler.briefing_time({"ICLAUDE_BRIEFING_AT": "late"}) is None


def test_compose_briefing():
    events = [caldav.Event("a", "Standup", datetime(2026, 10, 23, 8, 30, tzinfo=timezone.utc), False, "")]
    todays = [{"due": datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc).isoformat(), "text": "Call mum"}]
    text = scheduler.compose_briefing(NOW, TZ, events, todays, 3)
    assert text.splitlines() == ["Good morning. Here's Friday 23 October:", "", "Calendar:", "- 09:30 Standup",
                                 "", "Reminders today:", "- 17:00 Call mum", "", "GitHub: 3 unread notifications."]
    assert scheduler.compose_briefing(NOW, TZ, None, [], None).endswith("Nothing scheduled.")


def test_briefing_sends_once_per_day_at_the_set_time(tmp_path):
    a = agent(tmp_path, {"ICLAUDE_BRIEFING_AT": "08:00"})
    assert a.briefing(NOW - timedelta(minutes=1), "+15551234567", TZ) == ""
    assert a.briefing(NOW, "+15551234567", TZ).startswith("sent")
    assert a.briefing(NOW + timedelta(minutes=5), "+15551234567", TZ) == ""
    assert len(a.notifier.messages) == 1
    late = agent(tmp_path / "b", {"ICLAUDE_BRIEFING_AT": "08:00"})
    assert "skipped" in late.briefing(NOW + timedelta(hours=3), "+15551234567", TZ)


def test_watch_first_run_sets_cursor_then_alerts_once(tmp_path):
    class Source:
        name = "GitHub"

        def __init__(self):
            self.notices = []

        def fetch(self, since):
            return [n for n in self.notices if n.when > since]

    a = agent(tmp_path)
    source = Source()
    a.sources = [source]
    a.watch(NOW, "+15551234567")
    assert a.notifier.messages == []
    source.notices = [watchers.Notice("k1", NOW + timedelta(minutes=1), "review requested: o/r#1 x")]
    a.watch(NOW + timedelta(minutes=3), "+15551234567")
    a.watch(NOW + timedelta(minutes=6), "+15551234567")
    assert len(a.notifier.messages) == 1 and "GitHub: 1 update" in a.notifier.messages[0][1]


def test_calendar_heads_up_sent_once(tmp_path):
    a = agent(tmp_path)

    class Cal:
        def events(self, start, end, tz):
            return [caldav.Event("e", "Dentist", NOW + timedelta(minutes=10), False, "")]

    a.calendar = Cal()
    a.calendar_alerts(NOW, "+15551234567", TZ)
    a.calendar_alerts(NOW + timedelta(minutes=1), "+15551234567", TZ)
    assert [m[1] for m in a.notifier.messages] == ["In 10 min: Dentist at 08:10"]


def test_usage_warning_once_per_window(tmp_path, monkeypatch):
    import sys
    import types

    reset = int((NOW + timedelta(hours=2)).timestamp())
    module = types.SimpleNamespace(fetch_usage=lambda: {"five_hour": {"utilization": 85, "resets_at": reset}})
    monkeypatch.setitem(sys.modules, "inkbox_claude", types.ModuleType("inkbox_claude"))
    monkeypatch.setitem(sys.modules, "inkbox_claude.claude_usage", module)
    a = agent(tmp_path)
    a.usage_warning(NOW, "+15551234567")
    a.last.clear()
    a.usage_warning(NOW + timedelta(minutes=10), "+15551234567")
    assert len(a.notifier.messages) == 1
    assert a.notifier.messages[0][1].startswith("Heads-up: you've used 85% of your 5-hour Claude limit. It resets at ")


def test_tick_isolates_failures_and_skips_owner_jobs_without_a_phone(tmp_path):
    a = agent(tmp_path, {"INKBOX_ALLOWED_USERS": "me@icloud.com"})
    a.store.add("+15551234567", "x", NOW - timedelta(minutes=1), "none")
    a.tick(NOW, lambda prompt: "{}")
    assert "Reminders" in a.logged and "Email alerts" not in a.logged
    assert (tmp_path / "state.json").exists()
