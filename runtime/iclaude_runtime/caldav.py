"""Read-only CalDAV client for calendar heads-ups and the morning briefing (Fastmail by default)."""

from __future__ import annotations

import base64
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

FASTMAIL_CALDAV = "https://caldav.fastmail.com/dav/calendars/user/{user}/"
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}

PROPFIND = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:displayname/></d:prop></d:propfind>"""

QUERY = """<?xml version="1.0"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:prop><c:calendar-data><c:expand start="{start}" end="{end}"/></c:calendar-data></d:prop>
<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">
<c:time-range start="{start}" end="{end}"/></c:comp-filter></c:comp-filter></c:filter>
</c:calendar-query>"""


@dataclass
class Event:
    uid: str
    title: str
    start: datetime
    all_day: bool
    location: str

    @property
    def key(self) -> str:
        return f"{self.uid}@{self.start.isoformat()}"


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unescape(value: str) -> str:
    return value.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _parse_dt(value: str, params: dict[str, str], tz: ZoneInfo) -> tuple[datetime, bool]:
    if params.get("VALUE") == "DATE" or len(value) == 8:
        day = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        return datetime(day.year, day.month, day.day, tzinfo=tz), True
    parsed = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return parsed.replace(tzinfo=timezone.utc), False
    try:
        return parsed.replace(tzinfo=ZoneInfo(params.get("TZID", ""))), False
    except (KeyError, ValueError):
        return parsed.replace(tzinfo=tz), False


def parse_ics(text: str, tz: ZoneInfo) -> list[Event]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    events, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            if "DTSTART" in current and current.get("STATUS", ("",))[0].upper() != "CANCELLED":
                start, all_day = _parse_dt(current["DTSTART"][0], current["DTSTART"][1], tz)
                events.append(Event(current.get("UID", ("",))[0], _unescape(current.get("SUMMARY", ("(no title)",))[0]),
                                    start, all_day, _unescape(current.get("LOCATION", ("",))[0])))
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *raw_params = head.split(";")
            params = dict(p.split("=", 1) for p in raw_params if "=" in p)
            current.setdefault(name.upper(), (value, params))
    return events


class CalDAV:
    def __init__(self, user: str, password: str, url: str = "", opener: Callable = urllib.request.urlopen):
        self.user, self.password = user, password
        self.url = url or FASTMAIL_CALDAV.format(user=urllib.parse.quote(user))
        self.opener = opener
        self.calendars: list[str] | None = None

    def _request(self, url: str, method: str, body: str, depth: str = "1") -> ET.Element:
        auth = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        request = urllib.request.Request(url, data=body.encode(), method=method, headers={
            "Authorization": f"Basic {auth}", "Depth": depth, "Content-Type": "application/xml; charset=utf-8",
        })
        with self.opener(request, timeout=20) as response:
            return ET.fromstring(response.read())

    def discover(self) -> list[str]:
        if self.calendars is None:
            root = self._request(self.url, "PROPFIND", PROPFIND)
            found = []
            for response in root.findall("d:response", NS):
                if response.find(".//d:resourcetype/c:calendar", NS) is not None:
                    found.append(urllib.parse.urljoin(self.url, response.findtext("d:href", "", NS)))
            self.calendars = found
        return self.calendars

    def events(self, start: datetime, end: datetime, tz: ZoneInfo) -> list[Event]:
        body = QUERY.format(start=_stamp(start), end=_stamp(end))
        events: dict[str, Event] = {}
        try:
            for calendar in self.discover():
                root = self._request(calendar, "REPORT", body)
                for data in root.iter("{urn:ietf:params:xml:ns:caldav}calendar-data"):
                    for event in parse_ics(data.text or "", tz):
                        if start - timedelta(days=1) <= event.start < end:
                            events[event.key] = event
        except Exception:
            self.calendars = None
            raise
        return sorted(events.values(), key=lambda e: e.start)


def heads_up(events: list[Event], now: datetime, lead: timedelta, done: set[str], tz: ZoneInfo) -> list[tuple[Event, str]]:
    due = []
    for event in events:
        if event.all_day or event.key in done:
            continue
        if timedelta(0) <= event.start - now <= lead:
            minutes = max(1, round((event.start - now).total_seconds() / 60))
            where = f" ({event.location})" if event.location else ""
            due.append((event, f"In {minutes} min: {event.title} at {event.start.astimezone(tz).strftime('%H:%M')}{where}"))
    return due


def agenda(events: list[Event], day: date, tz: ZoneInfo) -> list[str]:
    lines = []
    for event in events:
        local = event.start.astimezone(tz)
        if local.date() != day:
            continue
        when = "All day" if event.all_day else local.strftime("%H:%M")
        lines.append(f"{when} {event.title}" + (f" ({event.location})" if event.location else ""))
    return lines
