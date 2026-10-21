"""Factory reset: forget conversations, memory and workspace files, keep logins and config."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

# Everything else under these directories is conversation or runtime state.
KEEP_INKBOX = {".env"}
KEEP_CLAUDE = {".credentials.json", "settings.json", "settings.local.json", "skills", "agents", "commands", "plugins"}


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _children(directory: Path, keep: set[str]) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.name not in keep)


def plan(home: Path, workspace: Path) -> list[Path]:
    targets = _children(home / ".inkbox-claude", KEEP_INKBOX) + _children(home / ".claude", KEEP_CLAUDE)
    return targets + _children(workspace, set())


def strip_project_history(config: Path) -> bool:
    """Drop per-project history from ~/.claude.json while keeping the account login in it."""
    try:
        data = json.loads(config.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or "projects" not in data:
        return False
    data.pop("projects")
    mode = config.stat().st_mode & 0o777
    config.write_text(json.dumps(data, indent=2))
    os.chmod(config, mode)
    return True


def reset_state(home: Path, workspace: Path) -> list[Path]:
    removed = plan(home, workspace)
    for path in removed:
        _remove(path)
    if strip_project_history(home / ".claude.json"):
        removed.append(home / ".claude.json")
    return removed
