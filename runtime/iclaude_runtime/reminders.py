"""Reminders and scheduled messages: set by texting Claude, delivered by iClaude without a Claude turn."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .notify import Notifier, authorised_phone, stable_key

STORE_FILE = Path.home() / ".iclaude" / "reminders.json"
REPEATS = ("none", "daily", "weekdays", "weekly")
MAX_PER_CONTACT = 50
MAX_TEXT = 500
LATE_GRACE = timedelta(hours=6)

_lock = threading.Lock()


def zone(tz: str | None = None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or os.environ.get("TZ") or "UTC")
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def parse_when(at: str | None, in_minutes: float | None, tz: ZoneInfo, now: datetime) -> datetime:
    if in_minutes is not None:
        minutes = float(in_minutes)
        if minutes <= 0:
            raise ValueError("in_minutes must be positive")
        return now + timedelta(minutes=minutes)
    if not at:
        raise ValueError("Give either 'at' or 'in_minutes'")
    when = datetime.fromisoformat(at.strip().replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=tz)
    when = when.astimezone(timezone.utc)
    if when <= now:
        raise ValueError(f"{at} is in the past")
    return when


def next_due(due: datetime, repeat: str, tz: ZoneInfo) -> datetime | None:
    if repeat == "none":
        return None
    local = due.astimezone(tz)
    step = 7 if repeat == "weekly" else 1
    nxt = (local.replace(tzinfo=None) + timedelta(days=step))
    if repeat == "weekdays":
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    return nxt.replace(tzinfo=tz).astimezone(timezone.utc)


def describe(item: dict, tz: ZoneInfo) -> str:
    when = datetime.fromisoformat(item["due"]).astimezone(tz)
    repeat = "" if item["repeat"] == "none" else f", repeats {item['repeat']}"
    return f"{item['id']}: {when.strftime('%a %d %b %H:%M %Z')}{repeat} - {item['text']}"


class Store:
    def __init__(self, path: Path = STORE_FILE):
        self.path = path

    def load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2))
        tmp.replace(self.path)

    def add(self, to: str, text: str, due: datetime, repeat: str) -> dict:
        text = " ".join(str(text).split())[:MAX_TEXT]
        if not text:
            raise ValueError("The reminder needs some text")
        if repeat not in REPEATS:
            raise ValueError(f"repeat must be one of {', '.join(REPEATS)}")
        with _lock:
            items = self.load()
            if sum(1 for i in items if i["to"] == to) >= MAX_PER_CONTACT:
                raise ValueError(f"You already have {MAX_PER_CONTACT} reminders; cancel some first")
            item = {"id": uuid.uuid4().hex[:6], "to": to, "text": text, "due": due.isoformat(), "repeat": repeat}
            self.save(items + [item])
        return item

    def list(self, to: str | None = None) -> list[dict]:
        items = [i for i in self.load() if to is None or i["to"] == to]
        return sorted(items, key=lambda i: i["due"])

    def cancel(self, reminder_id: str, to: str | None = None) -> bool:
        with _lock:
            items = self.load()
            kept = [i for i in items if not (i["id"] == reminder_id and (to is None or i["to"] == to))]
            if len(kept) == len(items):
                return False
            self.save(kept)
        return True

    def fire_due(self, now: datetime, notifier: Notifier, tz: ZoneInfo) -> int:
        """Send every due reminder once; repeating ones move to their next time."""
        sent = 0
        with _lock:
            items = self.load()
            for item in list(items):
                due = datetime.fromisoformat(item["due"])
                if due > now:
                    continue
                if now - due <= LATE_GRACE:
                    late = now - due > timedelta(minutes=5)
                    text = f"Reminder: {item['text']}" + (f" (was due {due.astimezone(tz).strftime('%H:%M')})" if late else "")
                    notifier.send(item["to"], text, stable_key("reminder", item["id"], item["due"]))
                    sent += 1
                nxt = next_due(due, item["repeat"], tz)
                while nxt is not None and nxt <= now:
                    nxt = next_due(nxt, item["repeat"], tz)
                if nxt is None:
                    items.remove(item)
                else:
                    item["due"] = nxt.isoformat()
                self.save(items)
        return sent


SCHEMAS = {
    "remind": ("Schedule a reminder or message that iClaude texts this person later by iMessage. Use for "
               "'remind me', 'text me at', 'every weekday at 8 tell me'. Times are the owner's local time "
               "({tz}) unless an offset is given. Give 'at' (ISO 8601, e.g. 2026-10-21T17:00) or 'in_minutes'.",
               {"type": "object", "properties": {
                   "text": {"type": "string", "description": "What the reminder should say"},
                   "at": {"type": "string", "description": "Local date and time, ISO 8601"},
                   "in_minutes": {"type": "number", "description": "Minutes from now, instead of 'at'"},
                   "repeat": {"type": "string", "enum": list(REPEATS), "description": "Default none"},
               }, "required": ["text"]}),
    "list_reminders": ("List this person's upcoming reminders.", {"type": "object", "properties": {}}),
    "cancel_reminder": ("Cancel one of this person's reminders by its id.",
                        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}),
}


def handlers(env_loader, store: Store, session_getter=None) -> dict:
    """Tool handlers that always act for the person in the current conversation."""
    from .hooks import current_session, session_contact

    def contact() -> str:
        person = session_contact((session_getter or current_session)())
        if not authorised_phone(env_loader(), person):
            raise PermissionError("Reminders are sent by iMessage, so ask for them from your authorised iPhone number.")
        return person

    def reply(text: str, error: bool = False) -> dict:
        return {"content": [{"type": "text", "text": text}], **({"is_error": True} if error else {})}

    async def remind(args):
        try:
            tz, now = zone(), datetime.now(timezone.utc)
            due = parse_when(args.get("at"), args.get("in_minutes"), tz, now)
            item = store.add(contact(), args["text"], due, args.get("repeat") or "none")
        except (ValueError, PermissionError) as exc:
            return reply(str(exc), error=True)
        return reply(f"Scheduled {describe(item, tz)}. Current local time is {now.astimezone(tz).strftime('%a %d %b %H:%M %Z')}.")

    async def list_reminders(args):
        try:
            items = store.list(contact())
        except PermissionError as exc:
            return reply(str(exc), error=True)
        tz = zone()
        return reply("\n".join(describe(i, tz) for i in items) or "No reminders set.")

    async def cancel_reminder(args):
        try:
            done = store.cancel(str(args.get("id", "")), contact())
        except PermissionError as exc:
            return reply(str(exc), error=True)
        return reply("Cancelled." if done else "No reminder with that id.", error=not done)

    return {"remind": remind, "list_reminders": list_reminders, "cancel_reminder": cancel_reminder}


def tool_server(env_loader, store: Store | None = None):
    """The in-process MCP server Claude uses to set reminders for the person it is talking to."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    tools = []
    for name, handler in handlers(env_loader, store or Store()).items():
        description, schema = SCHEMAS[name]
        tools.append(tool(name, description.format(tz=zone().key), schema)(handler))
    return create_sdk_mcp_server("iclaude", tools=tools), [t.name for t in tools]


def due_today(store: Store, to: str, now: datetime, tz: ZoneInfo) -> list[dict]:
    today = now.astimezone(tz).date()
    return [i for i in store.list(to) if datetime.fromisoformat(i["due"]).astimezone(tz).date() == today]
