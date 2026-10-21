import json
import os
from pathlib import Path

from iclaude_runtime import cli, reset


def build(tmp_path: Path) -> tuple[Path, Path]:
    home, workspace = tmp_path / "home", tmp_path / "workspace"
    files = {
        ".inkbox-claude/.env": "INKBOX_API_KEY=k",
        ".inkbox-claude/sessions.json": "{}",
        ".inkbox-claude/companion/state.json": "{}",
        ".inkbox-claude/media/a.jpg": "x",
        ".claude/.credentials.json": "{}",
        ".claude/settings.json": "{}",
        ".claude/skills/s/SKILL.md": "x",
        ".claude/CLAUDE.md": "mine",
        ".claude/projects/-workspace/abc.jsonl": "x",
        ".claude/projects/-workspace/memory/MEMORY.md": "x",
        ".claude/history.jsonl": "x",
        ".config/gh/hosts.yml": "x",
        ".gitconfig": "x",
    }
    for rel, text in files.items():
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "a@b.co"}, "projects": {"/workspace": {}}}))
    os.chmod(home / ".claude.json", 0o600)
    (workspace / "repo" / ".git").mkdir(parents=True)
    (workspace / ".hidden").write_text("x")
    return home, workspace


def test_reset_keeps_logins_and_config(tmp_path: Path):
    home, workspace = build(tmp_path)
    reset.reset_state(home, workspace)
    assert (home / ".inkbox-claude/.env").read_text() == "INKBOX_API_KEY=k"
    for kept in (".claude/.credentials.json", ".claude/settings.json", ".claude/skills/s/SKILL.md", ".config/gh/hosts.yml", ".gitconfig"):
        assert (home / kept).exists(), kept
    assert json.loads((home / ".claude.json").read_text()) == {"oauthAccount": {"emailAddress": "a@b.co"}}
    assert (home / ".claude.json").stat().st_mode & 0o777 == 0o600


def test_reset_removes_conversations_memory_and_workspace(tmp_path: Path):
    home, workspace = build(tmp_path)
    reset.reset_state(home, workspace)
    assert [p.name for p in (home / ".inkbox-claude").iterdir()] == [".env"]
    for gone in (".claude/CLAUDE.md", ".claude/projects", ".claude/history.jsonl"):
        assert not (home / gone).exists(), gone
    assert workspace.is_dir() and list(workspace.iterdir()) == []


def test_plan_only_lists(tmp_path: Path):
    home, workspace = build(tmp_path)
    targets = reset.plan(home, workspace)
    assert home / ".claude/projects" in targets and home / ".inkbox-claude/.env" not in targets
    assert (home / ".claude/projects").exists()


def test_reset_handles_missing_state(tmp_path: Path):
    assert reset.reset_state(tmp_path / "nohome", tmp_path / "nowork") == []


def test_cmd_reset_refuses_while_bridge_runs(tmp_path: Path, monkeypatch):
    home, workspace = build(tmp_path)
    monkeypatch.setattr(cli.Path, "home", lambda: home)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(workspace))
    monkeypatch.setattr(cli, "_probe", lambda path: {"ok": True})
    assert cli.cmd_reset(True) == 1
    assert (home / ".claude/projects").exists()
    monkeypatch.setattr(cli, "_probe", lambda path: None)
    assert cli.cmd_reset(True) == 0
    assert not (home / ".claude/projects").exists()
