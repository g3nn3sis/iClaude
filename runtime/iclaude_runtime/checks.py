"""Preflight checks that must pass before the bridge is allowed to start."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from . import approvals

TRUE_VALUES = {"1", "true", "yes", "on"}
PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def env_file_path() -> Path:
    return Path(os.getenv("INKBOX_CLAUDE_ENV_FILE") or Path.home() / ".inkbox-claude" / ".env")


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv file the same way the bridge daemon does."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def effective_env(path: Path | None = None) -> dict[str, str]:
    """Bridge view of the config: the real environment wins over the .env file."""
    merged = read_env_file(path or env_file_path())
    merged.update(os.environ)
    return merged


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def parse_contacts(raw: str) -> tuple[list[str], list[str]]:
    """Split a comma-separated allowlist into (valid, invalid) entries."""
    valid: list[str] = []
    invalid: list[str] = []
    for item in (part.strip() for part in raw.replace("\n", ",").split(",")):
        if not item:
            continue
        candidate = re.sub(r"[\s().-]", "", item) if item.startswith("+") else item.lower()
        if PHONE_RE.match(candidate) or EMAIL_RE.match(candidate):
            if candidate not in valid:
                valid.append(candidate)
        else:
            invalid.append(item)
    return valid, invalid


def check_claude_auth(runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Check:
    cli = shutil.which("claude")
    fix = "Run: ./iclaude login"
    if not cli:
        return Check("Claude login", False, "claude CLI is not installed in the image", "Rebuild: ./iclaude update")
    try:
        result = runner([cli, "auth", "status", "--json"], capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return Check("Claude login", False, "could not read `claude auth status`", fix)
    if result.returncode != 0 or data.get("loggedIn") is not True:
        return Check("Claude login", False, "not logged in", fix)
    method = data.get("authMethod") or "unknown"
    if data.get("apiKeySource") or method in {"api_key", "apiKey"}:
        return Check("Claude login", True, f"logged in with an API key ({method}); subscription login is recommended")
    plan = data.get("subscriptionType") or "subscription"
    return Check("Claude login", True, f"logged in ({plan}, {method})")


def check_inkbox_identity(env: Mapping[str, str]) -> Check:
    missing = [name for name in ("INKBOX_API_KEY", "INKBOX_IDENTITY") if not env.get(name)]
    if missing:
        return Check("Inkbox identity", False, f"missing {', '.join(missing)}", "Run: ./iclaude setup")
    return Check("Inkbox identity", True, env["INKBOX_IDENTITY"])


def check_signature(env: Mapping[str, str]) -> Check:
    if env.get("INKBOX_REQUIRE_SIGNATURE", "true").strip().lower() in {"0", "false", "no", "off"}:
        return Check("Webhook signatures", False, "INKBOX_REQUIRE_SIGNATURE is disabled",
                     "Remove INKBOX_REQUIRE_SIGNATURE=false from the bridge config")
    if not env.get("INKBOX_SIGNING_KEY"):
        return Check("Webhook signatures", False, "no INKBOX_SIGNING_KEY", "Run: ./iclaude setup")
    return Check("Webhook signatures", True, "required")


def check_allowlist(env: Mapping[str, str]) -> Check:
    fix = "Run: ./iclaude allow +15551234567 (your iMessage phone number or Apple ID email)"
    if is_true(env.get("INKBOX_ALLOW_ALL_USERS")):
        return Check("Authorised contacts", False, "INKBOX_ALLOW_ALL_USERS=true lets any contact in", fix)
    valid, invalid = parse_contacts(env.get("INKBOX_ALLOWED_USERS", ""))
    if invalid:
        return Check("Authorised contacts", False, f"invalid entries: {', '.join(invalid)}", fix)
    if not valid:
        return Check("Authorised contacts", False, "no contacts are authorised", fix)
    return Check("Authorised contacts", True, ", ".join(valid))


def _bypass_sources(paths: list[Path]) -> list[str]:
    found = []
    for path in paths:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        permissions = data.get("permissions") if isinstance(data, dict) else None
        if isinstance(permissions, dict) and permissions.get("defaultMode") == "bypassPermissions":
            found.append(str(path))
    return found


def check_permissions(home: Path, project_dir: Path, env: Mapping[str, str] | None = None) -> Check:
    candidates = [
        home / ".claude" / "settings.json",
        project_dir / ".claude" / "settings.json",
        project_dir / ".claude" / "settings.local.json",
    ]
    found = _bypass_sources(candidates)
    if found:
        return Check("Permission prompts", False, f"bypassPermissions set in {', '.join(found)}",
                     "Remove permissions.defaultMode=bypassPermissions; iClaude never disables approvals")
    on, unknown = approvals.parse((env or {}).get(approvals.SETTING))
    if unknown:
        return Check("Permission prompts", False, f"unknown auto-approve categories: {', '.join(unknown)}",
                     f"Rewrite it with ./iclaude approve on|off <{'|'.join(approvals.BY_NAME)}>")
    auto = f"; auto-approved: {', '.join(on)}" if on else ""
    return Check("Permission prompts", True, f"dangerous tools require approval by text{auto}")


def check_workspace(project_dir: Path) -> Check:
    if not project_dir.is_dir():
        return Check("Workspace", False, f"{project_dir} does not exist", "Check the workspace volume in compose.yaml")
    if not os.access(project_dir, os.W_OK):
        return Check("Workspace", False, f"{project_dir} is not writable by the container user",
                     "Fix ownership: the container runs as uid 1000")
    return Check("Workspace", True, str(project_dir))


def preflight(env: Mapping[str, str] | None = None) -> list[Check]:
    env = effective_env() if env is None else env
    project_dir = Path(env.get("CLAUDE_PROJECT_DIR") or "/workspace")
    return [
        check_claude_auth(),
        check_inkbox_identity(env),
        check_signature(env),
        check_allowlist(env),
        check_permissions(Path.home(), project_dir, env),
        check_workspace(project_dir),
    ]
