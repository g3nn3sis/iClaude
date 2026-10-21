"""In-container command dispatcher used as the image entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .checks import Check, effective_env, env_file_path, parse_contacts, preflight
from .defaults import memory_environment, seed_claude_md

GREEN, RED, YELLOW, BOLD, RESET = ("\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m") if sys.stdout.isatty() else ("",) * 5
WAIT_SECONDS = 30


def _print_checks(checks: list[Check]) -> None:
    for check in checks:
        mark = f"{GREEN}✓{RESET}" if check.ok else f"{RED}✗{RESET}"
        print(f"  {mark} {check.name}: {check.detail}")
        if not check.ok and check.fix:
            print(f"      {YELLOW}{check.fix}{RESET}")


def select_checks(checks: list[Check], names: list[str]) -> list[Check]:
    wanted = [n.lower() for n in names]
    return [c for c in checks if not wanted or any(c.name.lower().startswith(n) for n in wanted)]


def cmd_run() -> int:
    """Wait until preflight passes, then hand the process over to the bridge."""
    if seed_claude_md(Path.home()):
        print("Installed the default conversational ~/.claude/CLAUDE.md", flush=True)
    last = None
    while True:
        checks = preflight()
        failing = [c for c in checks if not c.ok]
        if not failing:
            break
        signature = [(c.name, c.detail) for c in failing]
        if signature != last:
            print("iClaude is waiting for setup to finish:", flush=True)
            _print_checks(failing)
            print(f"Rechecking every {WAIT_SECONDS}s.", flush=True)
            last = signature
        time.sleep(WAIT_SECONDS)
    print("iClaude preflight passed:", flush=True)
    _print_checks(checks)
    print(f"  Memory: {memory_environment(effective_env())}", flush=True)
    os.execvp("inkbox-claude", ["inkbox-claude", "run"])


def _save(name: str, value: str) -> None:
    from inkbox_claude import setup_wizard

    setup_wizard._save(name, value)


def cmd_allow(contacts: list[str], replace: bool, remove: bool) -> int:
    current, _ = parse_contacts(effective_env().get("INKBOX_ALLOWED_USERS", ""))
    requested, invalid = parse_contacts(",".join(contacts))
    if invalid:
        print(f"{RED}Not a phone number (+E.164) or email: {', '.join(invalid)}{RESET}")
        return 1
    if remove:
        updated = [c for c in current if c not in requested]
    elif replace:
        updated = requested
    else:
        updated = current + [c for c in requested if c not in current]
    _save("INKBOX_ALLOWED_USERS", ",".join(updated))
    _save("INKBOX_ALLOW_ALL_USERS", "false")
    print("Authorised contacts:", ", ".join(updated) if updated else "(none, the bridge will not start)")
    return 0


def _ask_allowlist() -> None:
    from inkbox_claude import setup_wizard as w

    print()
    print(w.color("  --- Who may talk to iClaude ---", w.Colors.CYAN))
    w.print_info("  iClaude only answers contacts you list here, on top of Inkbox contact rules.")
    w.print_info("  Use your iMessage phone number in +E.164 form (+15551234567) and/or Apple ID email.")
    current, _ = parse_contacts(effective_env().get("INKBOX_ALLOWED_USERS", ""))
    while True:
        raw = w.prompt("  Authorised contacts (comma-separated)", ",".join(current) or None).strip()
        valid, invalid = parse_contacts(raw)
        if invalid:
            w.print_error(f"  Not a phone number or email: {', '.join(invalid)}")
            continue
        if not valid:
            w.print_error("  At least one contact is required.")
            continue
        break
    _save("INKBOX_ALLOWED_USERS", ",".join(valid))
    _save("INKBOX_ALLOW_ALL_USERS", "false")
    w.print_success(f"  Only {', '.join(valid)} can reach iClaude.")


def cmd_setup() -> int:
    """Run the upstream Inkbox wizard with Docker-specific steps swapped in."""
    from inkbox_claude import setup_wizard as w

    def project_dir_step() -> None:
        w.print_info(f"  Claude Code works in {os.environ.get('CLAUDE_PROJECT_DIR', '/workspace')} (the persistent workspace volume).")

    def autostart_step() -> bool:
        w.print_info("  Docker keeps the bridge running and restarts it on boot; nothing to install here.")
        return False

    w._configure_project_dir = project_dir_step
    w._configure_autostart = autostart_step
    try:
        w.interactive_setup()
        _ask_allowlist()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. Rerun ./iclaude setup any time; finished steps are kept.")
        return 130
    print()
    checks = preflight()
    _print_checks(checks)
    if all(c.ok for c in checks):
        print(f"\n{GREEN}{BOLD}Ready.{RESET} Start iClaude with: ./iclaude start")
        return 0
    print("\nFix the items above, then run: ./iclaude start")
    return 1


def cmd_login() -> int:
    """Interactive Claude subscription login; credentials land on the home volume."""
    print("Sign in with your Claude Pro or Max account. Open the URL shown, approve, and paste the code back here.")
    code = subprocess.call(["claude", "auth", "login"])
    if code != 0:
        return code
    checks = preflight()
    _print_checks(checks[:1])
    return 0 if checks[0].ok else 1


def cmd_doctor() -> int:
    print(f"{BOLD}iClaude{RESET}")
    print(f"  bridge {os.environ.get('ICLAUDE_BRIDGE_REF', '?')[:12]}, {subprocess.run(['claude', '--version'], capture_output=True, text=True).stdout.strip()}")
    print(f"  config {env_file_path()}")
    checks = preflight()
    _print_checks(checks)
    ready = _probe("/ready")
    print(f"  {'✓' if ready and ready.get('ready') else '✗'} Bridge readiness: {json.dumps(ready) if ready else 'bridge is not running'}")
    print(f"\n{BOLD}Inkbox bridge doctor{RESET}")
    sys.stdout.flush()
    bridge = subprocess.call(["inkbox-claude", "doctor"])
    return 0 if all(c.ok for c in checks) and bridge == 0 else 1


def _probe(path: str) -> dict | None:
    port = effective_env().get("INKBOX_BRIDGE_PORT") or "8767"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=9) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read() or b"{}")
        except ValueError:
            return {"ready": False, "status": exc.code}
    except (OSError, ValueError):
        return None


def cmd_reset(confirmed: bool) -> int:
    from .reset import plan, reset_state

    home, workspace = Path.home(), Path(os.environ.get("CLAUDE_PROJECT_DIR", "/workspace"))
    if _probe("/health") is not None:
        print(f"{RED}The bridge is running. Use ./iclaude reset on the host, which stops it first.{RESET}")
        return 1
    if not confirmed:
        print("Would remove:")
        for path in plan(home, workspace):
            print(f"  {path}")
        print("Run with --yes to delete these.")
        return 0
    removed = reset_state(home, workspace)
    print(f"{GREEN}Reset complete{RESET}: removed {len(removed)} items. Logins and config were kept.")
    return 0


def cmd_healthcheck() -> int:
    result = _probe("/ready")
    return 0 if result and result.get("ready") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iclaude-container")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="wait for setup, then run the bridge in the foreground")
    sub.add_parser("setup", help="interactive Inkbox setup and contact allowlist")
    sub.add_parser("login", help="log in to Claude with a Pro/Max subscription")
    sub.add_parser("doctor", help="diagnose configuration and bridge health")
    check = sub.add_parser("check", help="run preflight checks only")
    check.add_argument("names", nargs="*", help="only these checks, e.g. claude, inkbox, webhook, authorised")
    sub.add_parser("healthcheck", help="Docker health probe")
    sub.add_parser("connectors", help="list the MCP connectors a bridged Claude session can reach")
    reset = sub.add_parser("reset", help="forget conversations, memory and workspace files; keep logins and config")
    reset.add_argument("--yes", action="store_true", help="delete (otherwise only list what would be removed)")
    allow = sub.add_parser("allow", help="authorise contacts (phone +E.164 or email)")
    allow.add_argument("contacts", nargs="*")
    allow.add_argument("--replace", action="store_true", help="replace the list instead of adding")
    allow.add_argument("--remove", action="store_true", help="remove the given contacts")
    args = parser.parse_args(argv)

    if args.command == "run":
        return cmd_run()
    if args.command == "setup":
        return cmd_setup()
    if args.command == "login":
        return cmd_login()
    if args.command == "doctor":
        return cmd_doctor()
    if args.command == "check":
        checks = select_checks(preflight(), args.names)
        _print_checks(checks)
        return 0 if all(c.ok for c in checks) else 1
    if args.command == "healthcheck":
        return cmd_healthcheck()
    if args.command == "reset":
        return cmd_reset(args.yes)
    if args.command == "connectors":
        from .connectors import report

        return report()
    if args.command == "allow":
        if not args.contacts:
            current = effective_env().get("INKBOX_ALLOWED_USERS", "")
            print("Authorised contacts:", current or "(none)")
            return 0
        return cmd_allow(args.contacts, args.replace, args.remove)
    return 2


if __name__ == "__main__":
    sys.exit(main())
