"""Run the Inkbox bridge with iClaude's additions, leaving the bridge itself unmodified."""

from __future__ import annotations

import sys
from pathlib import Path

from . import alerts, approvals, hooks, reminders, scheduler, usage
from .checks import effective_env
from .notify import owner


def main() -> int:
    usage.install()
    hooks.install(lambda: reminders.tool_server(effective_env), effective_env)
    env = effective_env()
    auto = approvals.enabled(env)
    print(f"Auto-approve: {', '.join(auto) if auto else 'off'} (change with ./iclaude approve)", flush=True)
    print(f"Claude Code auto mode: {'on' if approvals.auto_mode(Path.home()) else 'off'} (change with ./iclaude auto-mode)", flush=True)
    phone, problem = owner(env)
    conf = alerts.settings(env)
    if problem:
        print(f"Notifications are limited: {problem}", flush=True)
    elif conf.enabled:
        sources = "Inkbox inbox" + (" and Fastmail" if conf.fastmail_token else "")
        print(f"Email alerts: checking {sources} every {conf.interval}s, alerting {phone}", flush=True)
    scheduler.start(effective_env)
    from inkbox_claude.cli import main as bridge_main

    return bridge_main(["run"])


if __name__ == "__main__":
    sys.exit(main())
