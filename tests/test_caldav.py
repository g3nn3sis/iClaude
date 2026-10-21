import io
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from iclaude_runtime import caldav

TZ = ZoneInfo("Europe/London")
ICS = """BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:a\r
DTSTART:20261023T090000Z\r
SUMMARY:Stand\r
 up\r
LOCATION:Room 1\\, floor 2\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:b\r
DTSTART;VALUE=DATE:20261023\r
SUMMARY:Holiday\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:c\r
DTSTART;TZID=America/New_York:20261023T080000\r
SUMMARY:NY call\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:d\r
DTSTART:20261023T100000Z\r
STATUS:CANCELLED\r
SUMMARY:Gone\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_parse_ics_handles_folding_dates_timezones_and_cancellations():
    events = {e.uid: e for e in caldav.parse_ics(ICS, TZ)}
    assert set(events) == {"a", "b", "c"}
    assert events["a"].title == "Standup" and events["a"].location == "Room 1, floor 2"
    assert events["a"].start == datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)
    assert events["b"].all_day and events["b"].start.date() == date(2026, 10, 23)
    assert events["c"].start.astimezone(timezone.utc).hour == 12


def test_heads_up_once_inside_the_lead_window():
    events = caldav.parse_ics(ICS, TZ)
    now = datetime(2026, 10, 23, 8, 50, tzinfo=timezone.utc)
    due = caldav.heads_up(events, now, timedelta(minutes=15), set(), TZ)
    assert [text for _, text in due] == ["In 10 min: Standup at 10:00 (Room 1, floor 2)"]
    assert caldav.heads_up(events, now, timedelta(minutes=15), {due[0][0].key}, TZ) == []
    assert caldav.heads_up(events, now - timedelta(hours=1), timedelta(minutes=15), set(), TZ) == []


def test_agenda_lists_the_day():
    lines = caldav.agenda(caldav.parse_ics(ICS, TZ), date(2026, 10, 23), TZ)
    assert lines == ["10:00 Standup (Room 1, floor 2)", "All day Holiday", "13:00 NY call"]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_discover_and_query_over_caldav():
    calls = []
    propfind = b"""<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
      <d:response><d:href>/dav/calendars/user/me@x.com/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
      <d:response><d:href>/dav/calendars/user/me@x.com/Default/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/><c:calendar/></d:resourcetype></d:prop></d:propstat></d:response>
    </d:multistatus>"""
    report = ("""<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop>
      <c:calendar-data>""" + ICS.replace("&", "&amp;") + """</c:calendar-data></d:prop></d:propstat></d:response></d:multistatus>""").encode()

    def opener(request, timeout):
        calls.append((request.get_method(), request.full_url, request.headers.get("Authorization"), request.data))
        return Response(propfind if request.get_method() == "PROPFIND" else report)

    client = caldav.CalDAV("me@x.com", "pw", opener=opener)
    start = datetime(2026, 10, 23, tzinfo=timezone.utc)
    events = client.events(start, start + timedelta(days=1), TZ)
    assert [e.uid for e in events] == ["b", "a", "c"]
    assert calls[0][:2] == ("PROPFIND", "https://caldav.fastmail.com/dav/calendars/user/me%40x.com/")
    assert calls[1][:2] == ("REPORT", "https://caldav.fastmail.com/dav/calendars/user/me@x.com/Default/")
    assert calls[1][2].startswith("Basic ") and b'<c:expand start="20261023T000000Z"' in calls[1][3]
    client.events(start, start + timedelta(days=1), TZ)
    assert [c[0] for c in calls].count("PROPFIND") == 1
