import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from iclaude_runtime import alerts

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
ENV = {"INKBOX_ALLOWED_USERS": "+15551234567,me@icloud.com", "ICLAUDE_ALERTS": "true"}


def email(n, sender="jane@example.com", source="Inkbox", minutes=5):
    return alerts.Email(source, str(n), sender, f"Subject {n}", NOW - timedelta(minutes=minutes), f"Body {n}")


class Source:
    def __init__(self, name, emails, address=""):
        self.name, self.emails, self.address, self.calls = name, emails, address, []

    def fetch(self, since):
        self.calls.append(since)
        return list(self.emails)


def answer(*items):
    return lambda prompt: json.dumps({"alerts": [{"id": k, "why": w, "reply": r} for k, w, r in items]})


def test_settings_defaults_to_first_authorised_phone():
    conf = alerts.settings(ENV)
    assert (conf.enabled, conf.recipient, conf.interval, conf.model, conf.problem) == (True, "+15551234567", 30, "haiku", "")


@pytest.mark.parametrize("env, problem", [
    ({"INKBOX_ALLOWED_USERS": "me@icloud.com"}, "No phone number"),
    ({**ENV, "ICLAUDE_ALERT_TO": "+15550000000"}, "not an authorised contact"),
])
def test_settings_only_alerts_authorised_phones(env, problem):
    assert problem in alerts.settings(env).problem


def test_first_run_starts_from_now_without_alerting():
    state, source = {}, Source("Inkbox", [email(1)])
    summary, message = alerts.run_cycle(ENV, state, [source], answer(), None, now=NOW)
    assert message is None and source.calls == []
    assert state["since"]["Inkbox"] == NOW.isoformat()


def test_flags_and_sends_then_advances():
    state = {"since": {"Inkbox": (NOW - timedelta(hours=1)).isoformat()}}
    sent = []
    source = Source("Inkbox", [email(1), email(2, minutes=1)])
    summary, message = alerts.run_cycle(ENV, state, [source], answer(("Inkbox:2", "Wants a decision by Friday", "Friday works.")),
                                        lambda text, key: sent.append((text, key)), now=NOW)
    assert sent and sent[0][0] == message
    assert "Inkbox: jane@example.com" in message and "Suggested reply: Friday works." in message
    assert "Subject 1" not in message
    assert state["since"]["Inkbox"] == (NOW - timedelta(minutes=1)).isoformat()
    assert state["seen"] == ["Inkbox:1", "Inkbox:2"]
    alerts.run_cycle(ENV, state, [source], answer(("Inkbox:2", "again", "")), lambda t, k: sent.append(t), now=NOW)
    assert len(sent) == 1


def test_skips_own_and_authorised_senders():
    state = {"since": {"Inkbox": (NOW - timedelta(hours=1)).isoformat()}}
    asked = []
    source = Source("Inkbox", [email(1, "me@icloud.com"), email(2, "Agent <agent@inkboxmail.com>")], address="agent@inkboxmail.com")
    alerts.run_cycle(ENV, state, [source], lambda p: asked.append(p) or "{}", None, now=NOW)
    assert asked == []


def test_usage_limit_pauses_without_losing_mail():
    state = {"since": {"Inkbox": (NOW - timedelta(hours=1)).isoformat()}}

    def limited(prompt):
        raise alerts.UsageLimited(int((NOW + timedelta(hours=2)).timestamp()))

    alerts.run_cycle(ENV, state, [Source("Inkbox", [email(1)])], limited, None, now=NOW)
    assert state["paused_until"] == int((NOW + timedelta(hours=2)).timestamp())
    assert "seen" not in state or state["seen"] == []
    summary, _ = alerts.run_cycle(ENV, state, [Source("Inkbox", [email(1)])], answer(), None, now=NOW)
    assert summary.startswith("Paused")


def test_failures_retry_then_give_up():
    state = {"since": {"Inkbox": (NOW - timedelta(hours=1)).isoformat()}}
    source = Source("Inkbox", [email(1)])
    for _ in range(alerts.MAX_FAILURES - 1):
        with pytest.raises(ValueError):
            alerts.run_cycle(ENV, state, [source], lambda p: "no json", None, now=NOW)
    summary, _ = alerts.run_cycle(ENV, state, [source], lambda p: "no json", None, now=NOW)
    assert "gave up" in summary and state["seen"] == ["Inkbox:1"] and "failures" not in state


def test_source_error_keeps_its_cursor():
    class Broken(Source):
        def fetch(self, since):
            raise OSError("down")

    start = (NOW - timedelta(hours=1)).isoformat()
    state = {"since": {"Inkbox": start, "Fastmail": start}}
    summary, _ = alerts.run_cycle(ENV, state, [Source("Inkbox", []), Broken("Fastmail", [])], answer(), None, now=NOW)
    assert state["since"]["Fastmail"] == start and "Fastmail: OSError" in summary


def test_lookback_test_mode_does_not_touch_state():
    state = {}
    summary, message = alerts.run_cycle(ENV, state, [Source("Inkbox", [email(1)])], answer(("Inkbox:1", "Reply", "")),
                                        None, now=NOW, lookback=timedelta(hours=24))
    assert message and state == {"since": {}, "seen": []}


def test_parse_alerts_ignores_unknown_ids_and_strips_links():
    emails = [email(1)]
    text = 'Sure: {"alerts": [{"id": "Inkbox:1", "why": "Verify at https://evil.example/x now", "reply": ""},' \
           ' {"id": "Inkbox:9", "why": "made up"}]}'
    picked = alerts.parse_alerts(text, emails)
    assert len(picked) == 1 and picked[0][1] == "Verify at [link removed] now"
    with pytest.raises(ValueError):
        alerts.parse_alerts("nothing", emails)


def test_prompt_marks_content_untrusted_and_truncates():
    long = alerts.Email("Fastmail", "a", "x@y.z", "Hi", NOW, "A" * 10_000)
    prompt = alerts.build_prompt([long])
    assert "untrusted" in prompt and len(prompt) < 4000


def test_format_message_is_capped():
    many = [(email(i), "why " * 50, "reply " * 50) for i in range(40)]
    text = alerts.format_message(many)
    assert text.startswith("40 emails need you:") and len(text) <= alerts.SMS_LIMIT


def test_fastmail_fetch_reads_unseen_inbox_mail():
    calls = []
    responses = [
        {"apiUrl": "https://api.example/jmap", "primaryAccounts": {"urn:ietf:params:jmap:mail": "acc"}},
        {"methodResponses": [["Mailbox/query", {"ids": ["inbox1"]}, "m"]]},
        {"methodResponses": [["Email/query", {"ids": ["e1"]}, "q"], ["Email/get", {"list": [{
            "id": "e1", "from": [{"name": "Jane", "email": "jane@example.com"}], "subject": "Lunch?",
            "receivedAt": "2026-10-21T11:58:00Z", "textBody": [{"partId": "1"}], "bodyValues": {"1": {"value": "Free Friday?"}},
        }]}, "g"]]},
    ]

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout):
        calls.append((request.full_url, request.headers.get("Authorization"), request.data))
        return Response(json.dumps(responses[len(calls) - 1]).encode())

    [found] = alerts.FastmailSource("tok", opener).fetch(NOW - timedelta(hours=1))
    assert (found.key, found.sender, found.subject, found.body) == ("Fastmail:e1", "Jane <jane@example.com>", "Lunch?", "Free Friday?")
    assert all(auth == "Bearer tok" for _, auth, _ in calls)
    query = json.loads(calls[2][2])["methodCalls"][0][1]["filter"]
    assert query == {"inMailbox": "inbox1", "after": "2026-10-21T11:00:00Z", "notKeyword": "$seen"}


def test_state_round_trip(tmp_path):
    path = tmp_path / "d" / "alerts.json"
    alerts.save_state({"since": {"Inkbox": "x"}}, path)
    assert alerts.load_state(path) == {"since": {"Inkbox": "x"}}
    assert (path.parent.stat().st_mode & 0o777) == 0o700
    assert alerts.load_state(tmp_path / "missing.json") == {}


def test_interval_is_seconds_with_a_floor():
    assert alerts.settings({**ENV, "ICLAUDE_ALERT_INTERVAL": "5"}).interval == alerts.MIN_INTERVAL_SECONDS
    assert alerts.settings({**ENV, "ICLAUDE_ALERT_INTERVAL": "nope"}).interval == 30


def test_quiet_polls_never_call_claude():
    state = {"since": {"Inkbox": (NOW - timedelta(hours=1)).isoformat()}}
    asked = []
    for _ in range(5):
        alerts.run_cycle(ENV, state, [Source("Inkbox", [])], lambda p: asked.append(p), None, now=NOW)
    assert asked == []


def test_watch_reuses_sources_and_stops(monkeypatch):
    import threading

    made, stop = [], threading.Event()

    def fake_cycle(env, state, sources, ask, send):
        made.append(id(sources))
        if len(made) == 3:
            stop.set()
        return "Checked Inkbox: 0 new, 0 flagged.", None

    monkeypatch.setattr(alerts, "run_cycle", fake_cycle)
    monkeypatch.setattr(alerts, "load_state", lambda: {})
    monkeypatch.setattr(alerts, "save_state", lambda state: None)
    monkeypatch.setattr(alerts, "settings", lambda env: alerts.Settings(True, "+15551234567", 0, "haiku", "", ""))
    alerts.watch(lambda: ENV, stop, first_delay=0)
    assert len(made) == 3 and len(set(made)) == 1


def test_fastmail_caches_session_and_resets_on_error():
    calls = []

    class Fake(alerts.FastmailSource):
        def session(self):
            calls.append("session")
            return "api", "acc"

        def _request(self, url, payload=None):
            return {"methodResponses": [["Mailbox/query", {"ids": ["inbox"]}, "m"]]}

        def _fetch(self, api, account, inbox, since):
            if since is None:
                raise OSError("down")
            return []

    source = Fake("tok")
    source.fetch(NOW)
    source.fetch(NOW)
    assert calls == ["session"]
    with pytest.raises(OSError):
        source.fetch(None)
    source.fetch(NOW)
    assert calls == ["session", "session"]
