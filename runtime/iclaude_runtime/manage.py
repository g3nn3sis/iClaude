"""CLI for the unprompted features: alerts, briefing, reminders and voice."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from . import alerts, caldav, reminders, scheduler, watchers
from .checks import effective_env, is_true
from .notify import owner

GREEN, RED, BOLD, RESET = ("\033[32m", "\033[31m", "\033[1m", "\033[0m") if sys.stdout.isatty() else ("",) * 4
ALERT_ACTIONS = ["status", "on", "off", "test", "fastmail", "calendar", "github", "vercel", "cloudflare", "usage"]


def _save(name: str, value: str) -> None:
    from inkbox_claude import setup_wizard

    setup_wizard._save(name, value)


def _fail(message: str) -> int:
    print(f"{RED}{message}{RESET}")
    return 1


def _ok(message: str) -> int:
    print(f"{GREEN}{message}{RESET}")
    return 0


def _secret(label: str) -> str:
    return getpass.getpass(f"{label} (input hidden, empty to cancel): ").strip()


def register(sub) -> None:
    alert = sub.add_parser("alerts", help="iMessage alerts: email, calendar, usage, GitHub, Vercel, Cloudflare")
    alert.add_argument("action", nargs="?", default="status", choices=ALERT_ACTIONS)
    alert.add_argument("value", nargs="?", help="on/off, or a usage percentage")
    alert.add_argument("--to", help="phone number to notify (+E.164, must be an authorised contact)")
    alert.add_argument("--hours", type=float, default=24, help="test: how far back to look")
    alert.add_argument("--send", action="store_true", help="test: actually send the iMessage")
    alert.add_argument("--lead", type=float, help="calendar: minutes of notice before an event")
    brief = sub.add_parser("briefing", help="daily morning briefing by iMessage")
    brief.add_argument("action", nargs="?", default="status", choices=["status", "on", "off", "test"])
    brief.add_argument("--at", default="08:00", help="local time, HH:MM")
    remind = sub.add_parser("reminders", help="list or cancel reminders set by text")
    remind.add_argument("action", nargs="?", default="list", choices=["list", "cancel"])
    remind.add_argument("id", nargs="?")
    voice = sub.add_parser("voice", help="how phone calls are answered")
    voice.add_argument("action", nargs="?", default="status", choices=["status", "inkbox", "openai"])


def dispatch(args: argparse.Namespace) -> int | None:
    handlers = {"alerts": cmd_alerts, "briefing": cmd_briefing, "reminders": cmd_reminders, "voice": cmd_voice}
    handler = handlers.get(args.command)
    return handler(args) if handler else None


def cmd_alerts(args) -> int:
    env = effective_env()
    action, value = args.action, (args.value or "").lower()
    if action == "on":
        probe = {**env, "ICLAUDE_ALERTS": "true", **({"ICLAUDE_ALERT_TO": args.to} if args.to else {})}
        phone, problem = owner(probe)
        if problem:
            return _fail(problem)
        if args.to:
            _save("ICLAUDE_ALERT_TO", args.to)
        _save("ICLAUDE_ALERTS", "true")
        return _ok(f"Email alerts on. Notifications go to {phone} as iMessages.")
    if action == "off":
        _save("ICLAUDE_ALERTS", "false")
        return _ok("Email alerts off.")
    if action == "test":
        return _alerts_test(env, args)
    if action == "fastmail":
        return _fastmail(value)
    if action == "calendar":
        return _calendar(value, args.lead)
    if action == "github":
        return _github(value)
    if action == "vercel":
        return _vercel(value)
    if action == "cloudflare":
        return _cloudflare(value)
    if action == "usage":
        return _usage(value)
    return _status(env)


def _status(env) -> int:
    phone, problem = owner(env)
    conf = alerts.settings(env)
    threshold = scheduler.usage_threshold(env)
    state = alerts.load_state()
    print(f"{BOLD}Notifications go to:{RESET} {phone or '(none)'}" + (f"  {RED}{problem}{RESET}" if problem else ""))
    rows = [
        ("Email", conf.enabled, f"Inkbox inbox{', Fastmail' if conf.fastmail_token else ''}, every {conf.interval}s"
         + (f", last check {state['last_run']}" if state.get("last_run") else ""), "iclaude alerts on"),
        ("Calendar", bool(env.get("ICLAUDE_CALDAV_USER")), f"{env.get('ICLAUDE_CALENDAR_LEAD') or 15} min before events",
         "iclaude alerts calendar"),
        ("Usage", threshold is not None, f"warn at {threshold:g}%" if threshold else "", "iclaude alerts usage on"),
        ("GitHub", is_true(env.get("ICLAUDE_GITHUB_ALERTS")), "review requests, mentions, CI", "iclaude alerts github on"),
        ("Vercel", bool(env.get("VERCEL_TOKEN")), "failed deploys", "iclaude alerts vercel"),
        ("Cloudflare", bool(env.get("CLOUDFLARE_API_TOKEN")), "failed Pages deploys", "iclaude alerts cloudflare"),
        ("Briefing", scheduler.briefing_time(env) is not None, f"daily at {env.get('ICLAUDE_BRIEFING_AT')}", "iclaude briefing on"),
    ]
    for name, on, detail, hint in rows:
        mark = f"{GREEN}on {RESET}" if on else "off"
        print(f"  {name:<11}{mark}  {detail if on else 'turn on: ' + hint}")
    print("Polling uses no Claude usage. Only new email is read by Claude (one small Haiku turn).")
    return 0


def _alerts_test(env, args) -> int:
    phone, problem = owner(env)
    conf = alerts.settings(env)
    if problem and args.send:
        return _fail(problem)
    send = None
    if args.send:
        from .notify import Notifier

        notifier = Notifier(env)
        send = lambda text, key, context: notifier.send(phone, text, key, context)  # noqa: E731
    summary, message = alerts.run_cycle(
        env, {}, alerts.make_sources(env, conf),
        lambda prompt: asyncio.run(alerts.ask_claude(prompt, conf.model)),
        send, lookback=timedelta(hours=args.hours),
    )
    print(summary)
    print(("Sent:" if args.send else "Would send:") + "\n\n" + message if message else "No email needs your attention.")
    return 0


def _fastmail(value: str) -> int:
    if value == "off":
        _save("FASTMAIL_API_TOKEN", "")
        return _ok("Fastmail removed from email alerts.")
    print("Create a token at Fastmail > Settings > Privacy & Security > API tokens, with read-only Email access.")
    token = _secret("Fastmail API token")
    if not token:
        return _fail("Nothing was saved.")
    try:
        alerts.FastmailSource(token).session()
    except Exception as exc:
        return _fail(f"Fastmail rejected the token ({type(exc).__name__}). Nothing was saved.")
    _save("FASTMAIL_API_TOKEN", token)
    return _ok("Fastmail connected. New inbox mail is included in email alerts.")


def _calendar(value: str, lead: float | None) -> int:
    if value == "off":
        _save("ICLAUDE_CALDAV_PASSWORD", "")
        _save("ICLAUDE_CALDAV_USER", "")
        return _ok("Calendar heads-ups off.")
    if lead is not None:
        _save("ICLAUDE_CALENDAR_LEAD", str(max(0, int(lead))))
        if value != "setup" and effective_env().get("ICLAUDE_CALDAV_USER"):
            return _ok(f"Calendar heads-ups {int(lead)} minutes before events.")
    print("Fastmail: create an app password at Settings > Privacy & Security > App passwords,")
    print("with access to Calendars (CalDAV) only. Other providers: set ICLAUDE_CALDAV_URL first.")
    user = input("Calendar username (your Fastmail email address): ").strip()
    password = _secret("App password")
    if not user or not password:
        return _fail("Nothing was saved.")
    client = caldav.CalDAV(user, password, effective_env().get("ICLAUDE_CALDAV_URL", ""))
    try:
        calendars = client.discover()
    except Exception as exc:
        return _fail(f"Could not read the calendar ({type(exc).__name__}). Nothing was saved.")
    if not calendars:
        return _fail("Signed in, but found no calendars. Nothing was saved.")
    _save("ICLAUDE_CALDAV_USER", user)
    _save("ICLAUDE_CALDAV_PASSWORD", password)
    return _ok(f"Calendar connected ({len(calendars)} calendars). iClaude only reads it.")


def _github(value: str) -> int:
    if value == "off":
        _save("ICLAUDE_GITHUB_ALERTS", "false")
        return _ok("GitHub alerts off.")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        return _fail("gh is not logged in. Run: iclaude shell, then gh auth login (needs the notifications scope).")
    try:
        watchers.GitHub().fetch(datetime.now(timezone.utc) - timedelta(minutes=1))
    except Exception:
        return _fail("gh cannot read notifications. Run gh auth refresh -s notifications in iclaude shell.")
    _save("ICLAUDE_GITHUB_ALERTS", "true")
    return _ok("GitHub alerts on: review requests, mentions, assignments, CI runs and security alerts.")


def _vercel(value: str) -> int:
    if value == "off":
        _save("VERCEL_TOKEN", "")
        return _ok("Vercel alerts off.")
    print("Create a token at vercel.com > Account Settings > Tokens.")
    token = _secret("Vercel token")
    if not token:
        return _fail("Nothing was saved.")
    team = input("Team ID (empty for your personal account): ").strip()
    try:
        watchers.Vercel(token, team).check()
    except Exception as exc:
        return _fail(f"Vercel rejected the token ({type(exc).__name__}). Nothing was saved.")
    _save("VERCEL_TOKEN", token)
    _save("VERCEL_TEAM_ID", team)
    return _ok("Vercel alerts on: you'll get a text when a deploy fails.")


def _cloudflare(value: str) -> int:
    if value == "off":
        _save("CLOUDFLARE_API_TOKEN", "")
        return _ok("Cloudflare alerts off.")
    print("Create a token at dash.cloudflare.com > My Profile > API Tokens with 'Cloudflare Pages: Read'.")
    token = _secret("Cloudflare API token")
    account = input("Account ID (on the dashboard's overview page): ").strip()
    if not token or not account:
        return _fail("Nothing was saved.")
    try:
        watchers.CloudflarePages(token, account).check()
    except Exception as exc:
        return _fail(f"Cloudflare rejected the token ({type(exc).__name__}). Nothing was saved.")
    _save("CLOUDFLARE_API_TOKEN", token)
    _save("CLOUDFLARE_ACCOUNT_ID", account)
    return _ok("Cloudflare alerts on: you'll get a text when a Pages deploy fails.")


def _usage(value: str) -> int:
    if value == "off":
        _save("ICLAUDE_USAGE_WARN", "off")
        return _ok("Usage warnings off.")
    percent = value if value.replace(".", "", 1).isdigit() else "80"
    _save("ICLAUDE_USAGE_WARN", percent)
    return _ok(f"You'll get a text when a Claude limit passes {percent}%.")


def cmd_briefing(args) -> int:
    env = effective_env()
    if args.action == "off":
        _save("ICLAUDE_BRIEFING_AT", "")
        return _ok("Morning briefing off.")
    if args.action == "on":
        if scheduler.briefing_time({"ICLAUDE_BRIEFING_AT": args.at}) is None:
            return _fail("Use HH:MM, for example --at 07:30.")
        phone, problem = owner(env)
        if problem:
            return _fail(problem)
        _save("ICLAUDE_BRIEFING_AT", args.at)
        return _ok(f"Morning briefing on: {args.at} every day to {phone}.")
    if args.action == "test":
        phone, _ = owner(env)
        agent = scheduler.Agent(env)
        print(agent.briefing_text(datetime.now(timezone.utc), phone, reminders.zone(env.get("TZ"))))
        return 0
    at = scheduler.briefing_time(env)
    print(f"Morning briefing: {'daily at ' + at.strftime('%H:%M') if at else 'off (iclaude briefing on --at 08:00)'}")
    return 0


def cmd_reminders(args) -> int:
    store, tz = reminders.Store(), reminders.zone()
    if args.action == "cancel":
        if not args.id:
            return _fail("Usage: iclaude reminders cancel <id>")
        return _ok("Cancelled.") if store.cancel(args.id) else _fail("No reminder with that id.")
    items = store.list()
    print("\n".join(f"{i['to']}  {reminders.describe(i, tz)}" for i in items) or "No reminders. Text iClaude \"remind me ...\" to set one.")
    return 0


def cmd_voice(args) -> int:
    env = effective_env()
    if args.action == "inkbox":
        from inkbox_claude.config import VoiceStack
        from inkbox_claude.setup_wizard import _save_voice_stack

        _save_voice_stack(VoiceStack.INKBOX_TTS_STT)
        return _ok("Calls use Inkbox speech-to-text and text-to-speech.")
    if args.action == "openai":
        from inkbox_claude.config import VoiceStack
        from inkbox_claude.setup_wizard import _save_voice_stack

        print("OpenAI Realtime gives a natural voice. Call audio is sent to OpenAI, and usage is billed to your OpenAI account.")
        key = _secret("OpenAI API key")
        if not key:
            return _fail("Nothing was saved.")
        if not openai_key_works(key):
            return _fail("OpenAI rejected the key. Nothing was saved.")
        _save_voice_stack(VoiceStack.OPENAI_REALTIME, realtime_api_key=key)
        return _ok("Calls now use OpenAI Realtime, falling back to Inkbox voice if it fails.")
    stack = env.get("INKBOX_VOICE_STACK") or ("openai_realtime" if is_true(env.get("INKBOX_REALTIME_ENABLED")) else "inkbox_tts_stt")
    labels = {"inkbox_tts_stt": "Inkbox speech-to-text and text-to-speech", "openai_realtime": "OpenAI Realtime",
              "inkbox_voice_ai": "Inkbox Voice AI"}
    print(f"Calls: {labels.get(stack, stack)}")
    print("Call the same iMessage contact you text, from an authorised number.")
    print("Change with: iclaude voice openai (natural voice, needs an OpenAI key) or iclaude voice inkbox")
    return 0


def openai_key_works(key: str) -> bool:
    import urllib.request

    request = urllib.request.Request("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status == 200
    except Exception:
        return False
