"""First-run defaults: the conversational CLAUDE.md and memory isolation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping, MutableMapping

from .checks import is_true, parse_contacts

DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "defaults"


def seed_claude_md(home: Path, source: Path = DEFAULTS_DIR / "CLAUDE.md") -> bool:
    """Install the default user-level CLAUDE.md unless one already exists."""
    target = home / ".claude" / "CLAUDE.md"
    if target.exists() or not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return True


def memory_environment(env: Mapping[str, str], process_env: MutableMapping[str, str] = os.environ) -> str:
    """Keep Claude's shared auto memory off when several contacts can reach the agent.

    Sessions and Inkbox contact memories are per contact, but Claude Code's auto memory is
    per project directory, so with more than one contact it would leak facts between them.
    """
    contacts, _ = parse_contacts(env.get("INKBOX_ALLOWED_USERS", ""))
    if len(contacts) <= 1:
        return "auto memory on (single owner contact)"
    if is_true(env.get("ICLAUDE_SHARED_MEMORY")):
        return "auto memory on and shared by all contacts (ICLAUDE_SHARED_MEMORY=true)"
    process_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return f"auto memory off: {len(contacts)} contacts share this workspace (set ICLAUDE_SHARED_MEMORY=true to allow)"
