"""One background thread for everything iClaude does unprompted. Only email triage ever uses Claude."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from . import alerts, caldav, reminders, usage, watchers
from .checks import is_true
from .notify import Notifier, owner, stable_key

log = logging.getLogger("iclaude.scheduler")

STATE_FILE = Path.home() / ".iclaude" / "state.json"
TICK_SECONDS = 15
CALENDAR_REFRESH = timedelta(minutes=10)
USAGE_EVERY = timedelta(minutes=5)
WATCH_EVERY = {"GitHub": timedelta(minutes=2), "Vercel": timedelta(minutes=3), "Cloudflare": timedelta(minutes=5)}
KEEP_KEYS = 300
CONFIG_KEYS = (
    "INKBOX_API_KEY", "INKBOX_IDENTITY", "INKBOX_ALLOWED_USERS", "ICLAUDE_ALERT_TO", "FASTMAIL_API_TOKEN",
    "ICLAUDE_CALDAV_USER", "ICLAUDE_CALDAV_PASSWORD", "ICLAUDE_CALDAV_URL", "ICLAUDE_GITHUB_ALERTS",
    "VERCEL_TOKEN", "VERCEL_TEAM_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
)


def calendar_client(env: Mapping[str, str]) -> caldav.CalDAV | None:
    user, password = env.get("ICLAUDE_CALDAV_USER", ""), env.get("ICLAUDE_CALDAV_PASSWORD", "")
    return caldav.CalDAV(user, password, env.get("ICLAUDE_CALDAV_URL", "")) if user and password else None


def watch_sources(env: Mapping[str, str]) -> list:
    sources: list = []
    if is_true(env.get("ICLAUDE_GITHUB_ALERTS")):
        sources.append(watchers.GitHub())
    if env.get("VERCEL_TOKEN"):
        sources.append(watchers.Vercel(env["VERCEL_TOKEN"], env.get("VERCEL_TEAM_ID", "")))
    if env.get("CLOUDFLARE_API_TOKEN") and env.get("CLOUDFLARE_ACCOUNT_ID"):
        sources.append(watchers.CloudflarePages(env["CLOUDFLARE_API_TOKEN"], env["CLOUDFLARE_ACCOUNT_ID"]))
    return sources


def usage_threshold(env: Mapping[str, str]) -> float | None:
    raw = (env.get("ICLAUDE_USAGE_WARN") or "80").strip().lower()
    if raw in ("off", "false", "0", "no"):
        return None
    try:
        return min(99.0, max(1.0, float(raw)))
    except ValueError:
        return 80.0


def briefing_time(env: Mapping[str, str]) -> dtime | None:
    raw = (env.get("ICLAUDE_BRIEFING_AT") or "").strip()
    try:
        return dtime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def compose_briefing(now: datetime, tz, events: list[caldav.Event] | None, todays: list[dict], github: int | None) -> str:
    local = now.astimezone(tz)
    lines = [f"Good morning. Here's {local.strftime('%A %d %B')}:"]
    if events is not None:
        agenda = caldav.agenda(events, local.date(), tz)
        lines += ["", "Calendar:"] + [f"- {a}" for a in agenda] if agenda else ["", "Nothing on your calendar."]
    if todays:
        lines += ["", "Reminders today:"]
        lines += [f"- {datetime.fromisoformat(i['due']).astimezone(tz).strftime('%H:%M')} {i['text']}" for i in todays]
    if github:
        lines += ["", f"GitHub: {github} unread notification{'s' if github != 1 else ''}."]
    if len(lines) == 1:
        lines.append("Nothing scheduled.")
    return "\n".join(lines)


class Agent:
    def __init__(self, env: Mapping[str, str], state_path: Path = STATE_FILE):
        self.env = env
        self.state_path = state_path
        self.notifier = Notifier(env)
        self.store = reminders.Store()
        self.calendar = calendar_client(env)
        self.events: list[caldav.Event] = []
        self.sources = watch_sources(env)
        conf = alerts.settings(env)
        self.mail_sources = alerts.make_sources(env, conf)
        self.last: dict[str, datetime] = {}
        self.logged: dict[str, str] = {}
        self.state = self.load()

    def load(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self) -> None:
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        tmp.replace(self.state_path)

    def due(self, name: str, every: timedelta, now: datetime) -> bool:
        if now - self.last.get(name, datetime.min.replace(tzinfo=timezone.utc)) < every:
            return False
        self.last[name] = now
        return True

    def report(self, name: str, summary: str) -> None:
        if self.logged.get(name) != summary:
            log.info("%s: %s", name, summary)
            self.logged[name] = summary

    def remember(self, bucket: str, key: str) -> None:
        keys = self.state.setdefault(bucket, [])
        keys.append(key)
        del keys[:-KEEP_KEYS]

    def tick(self, now: datetime, ask: Callable[[str], str]) -> None:
        phone, problem = owner(self.env)
        tz = reminders.zone(self.env.get("TZ"))
        jobs = [("Reminders", lambda: self.reminders(now, tz))]
        if not problem:
            jobs += [
                ("Email alerts", lambda: self.email(now, phone, ask)),
                ("Calendar", lambda: self.calendar_alerts(now, phone, tz)),
                ("Usage", lambda: self.usage_warning(now, phone)),
                ("Watchers", lambda: self.watch(now, phone)),
                ("Briefing", lambda: self.briefing(now, phone, tz)),
            ]
        for name, job in jobs:
            try:
                summary = job()
            except Exception as exc:
                summary = f"failed: {type(exc).__name__}"
            if summary:
                self.report(name, summary)
        self.save()

    def reminders(self, now: datetime, tz) -> str:
        sent = self.store.fire_due(now, self.notifier, tz)
        return f"sent {sent}" if sent else ""

    def email(self, now: datetime, phone: str, ask) -> str:
        conf = alerts.settings(self.env)
        if not conf.enabled or not self.due("email", timedelta(seconds=conf.interval), now):
            return ""
        state = alerts.load_state()
        try:
            summary, _ = alerts.run_cycle(self.env, state, self.mail_sources, ask,
                                          lambda text, key, context: self.notifier.send(phone, text, key, context), now=now)
        finally:
            alerts.save_state(state)
        return summary

    def calendar_alerts(self, now: datetime, phone: str, tz) -> str:
        if self.calendar is None:
            return ""
        if self.due("calendar", CALENDAR_REFRESH, now):
            self.events = self.calendar.events(now - timedelta(hours=1), now + timedelta(hours=36), tz)
        try:
            lead = timedelta(minutes=float(self.env.get("ICLAUDE_CALENDAR_LEAD") or 15))
        except ValueError:
            lead = timedelta(minutes=15)
        if lead <= timedelta(0):
            return ""
        done = set(self.state.get("calendar_done", []))
        for event, text in caldav.heads_up(self.events, now, lead, done, tz):
            self.notifier.send(phone, text, stable_key("calendar", event.key))
            self.remember("calendar_done", event.key)
        return f"{len(self.events)} upcoming events"

    def usage_warning(self, now: datetime, phone: str) -> str:
        threshold = usage_threshold(self.env)
        if threshold is None or not self.due("usage", USAGE_EVERY, now):
            return ""
        from inkbox_claude.claude_usage import fetch_usage

        warned = set(self.state.get("usage_warned", []))
        for key, text in usage.warnings(fetch_usage(), threshold, warned, self.env.get("TZ")):
            self.notifier.send(phone, text, stable_key("usage", key))
            self.remember("usage_warned", key)
        return "checked"

    def watch(self, now: datetime, phone: str) -> str:
        cursors = self.state.setdefault("watch_since", {})
        results = []
        for source in self.sources:
            if not self.due(source.name, WATCH_EVERY[source.name], now):
                continue
            since = watchers._parse(cursors.get(source.name))
            if since is None:
                cursors[source.name] = now.isoformat()
                continue
            seen = set(self.state.get("watch_seen", []))
            notices = [n for n in source.fetch(since) if n.key not in seen]
            if notices:
                text = watchers.format_notices(source.name, notices)
                self.notifier.send(phone, text, stable_key("watch", *[n.key for n in notices]))
                for notice in notices:
                    self.remember("watch_seen", notice.key)
                cursors[source.name] = max(n.when for n in notices).isoformat()
            results.append(f"{source.name} {len(notices)} new")
        return ", ".join(results)

    def briefing(self, now: datetime, phone: str, tz) -> str:
        at = briefing_time(self.env)
        local = now.astimezone(tz)
        if at is None or local.time() < at or self.state.get("briefing_date") == local.date().isoformat():
            return ""
        if local - datetime.combine(local.date(), at, tz) > timedelta(hours=2):
            self.state["briefing_date"] = local.date().isoformat()
            return "skipped (more than 2 hours late)"
        self.state["briefing_date"] = local.date().isoformat()
        self.notifier.send(phone, self.briefing_text(now, phone, tz), stable_key("briefing", local.date().isoformat()))
        return f"sent for {local.date().isoformat()}"

    def briefing_text(self, now: datetime, phone: str, tz) -> str:
        events = None
        if self.calendar is not None:
            local = now.astimezone(tz)
            start = datetime.combine(local.date(), dtime(0), tz)
            events = self.calendar.events(start, start + timedelta(days=1), tz)
        github = None
        if is_true(self.env.get("ICLAUDE_GITHUB_ALERTS")):
            github = github_unread()
        return compose_briefing(now, tz, events, reminders.due_today(self.store, phone, now, tz), github)


def github_unread() -> int | None:
    import subprocess

    result = subprocess.run(["gh", "api", "notifications", "--jq", "length"], capture_output=True, text=True, timeout=30)
    return int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else None


def config_signature(env: Mapping[str, str]) -> tuple:
    return tuple(env.get(k, "") for k in CONFIG_KEYS)


def run(env_loader: Callable[[], Mapping[str, str]], stop: threading.Event, first_delay: float = 20) -> None:
    stop.wait(first_delay)
    agent, signature = None, None
    while not stop.is_set():
        env = env_loader()
        if config_signature(env) != signature:
            agent, signature = Agent(env), config_signature(env)
        agent.env = env
        conf = alerts.settings(env)
        agent.tick(datetime.now(timezone.utc), lambda prompt: asyncio.run(alerts.ask_claude(prompt, conf.model)))
        stop.wait(TICK_SECONDS)


def start(env_loader: Callable[[], Mapping[str, str]]) -> threading.Thread:
    thread = threading.Thread(target=run, args=(env_loader, threading.Event()), name="iclaude-scheduler", daemon=True)
    thread.start()
    return thread
