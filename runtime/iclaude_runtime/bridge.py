"""Run the Inkbox bridge with iClaude's additions: the usage-limit reply and email alerts."""

from __future__ import annotations

import sys

from . import alerts, usage
from .checks import effective_env


def main() -> int:
    usage.install()
    conf = alerts.settings(effective_env())
    if conf.enabled and conf.problem:
        print(f"Email alerts are on but cannot run: {conf.problem}", flush=True)
    elif conf.enabled:
        sources = "Inkbox inbox" + (" and Fastmail" if conf.fastmail_token else "")
        print(f"Email alerts: checking {sources} every {conf.interval} min, alerting {conf.recipient}", flush=True)
        alerts.start_background(effective_env)
    from inkbox_claude.cli import main as bridge_main

    return bridge_main(["run"])


if __name__ == "__main__":
    sys.exit(main())
