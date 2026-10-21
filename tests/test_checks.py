import json
import subprocess
from pathlib import Path

import pytest

from iclaude_runtime import checks


def completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


@pytest.mark.parametrize(
    ("raw", "valid", "invalid"),
    [
        ("+15551234567", ["+15551234567"], []),
        ("+1 (555) 123-4567, Me@Example.com", ["+15551234567", "me@example.com"], []),
        ("+15551234567,+15551234567", ["+15551234567"], []),
        ("5551234567", [], ["5551234567"]),
        ("not-an-email, +1", [], ["not-an-email", "+1"]),
        ("", [], []),
    ],
)
def test_parse_contacts(raw, valid, invalid):
    assert checks.parse_contacts(raw) == (valid, invalid)


def test_read_env_file_matches_bridge_parser(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("# comment\nexport A=1\nB='two'\nC=\"three\"\nnot a pair\n\nD=x=y\n")
    assert checks.read_env_file(env) == {"A": "1", "B": "two", "C": "three", "D": "x=y"}


def test_read_env_file_missing(tmp_path: Path):
    assert checks.read_env_file(tmp_path / "missing") == {}


def test_real_environment_wins_over_env_file(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("CLAUDE_PROJECT_DIR=/elsewhere\nINKBOX_IDENTITY=from-file\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/workspace")
    merged = checks.effective_env(env)
    assert merged["CLAUDE_PROJECT_DIR"] == "/workspace"
    assert merged["INKBOX_IDENTITY"] == "from-file"


def test_allowlist_rejects_allow_all():
    result = checks.check_allowlist({"INKBOX_ALLOW_ALL_USERS": "true", "INKBOX_ALLOWED_USERS": "+15551234567"})
    assert not result.ok
    assert "any contact" in result.detail


def test_allowlist_rejects_empty_list():
    # The bridge treats an empty list as "allow everyone"; iClaude must refuse that.
    assert not checks.check_allowlist({"INKBOX_ALLOW_ALL_USERS": "false"}).ok


def test_allowlist_rejects_invalid_entries():
    assert not checks.check_allowlist({"INKBOX_ALLOWED_USERS": "+15551234567,bob"}).ok


def test_allowlist_accepts_explicit_contacts():
    result = checks.check_allowlist({"INKBOX_ALLOW_ALL_USERS": "false", "INKBOX_ALLOWED_USERS": "+15551234567"})
    assert result.ok


@pytest.mark.parametrize("value", ["false", "0", "no", "OFF"])
def test_signature_cannot_be_disabled(value):
    assert not checks.check_signature({"INKBOX_SIGNING_KEY": "k", "INKBOX_REQUIRE_SIGNATURE": value}).ok


def test_signature_requires_signing_key():
    assert not checks.check_signature({}).ok
    assert checks.check_signature({"INKBOX_SIGNING_KEY": "k"}).ok


def test_inkbox_identity():
    assert not checks.check_inkbox_identity({"INKBOX_API_KEY": "k"}).ok
    assert checks.check_inkbox_identity({"INKBOX_API_KEY": "k", "INKBOX_IDENTITY": "agent"}).ok


def test_permissions_detect_bypass(tmp_path: Path):
    home, project = tmp_path / "home", tmp_path / "work"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
    result = checks.check_permissions(home, project)
    assert not result.ok
    assert "settings.local.json" in result.detail


def test_permissions_ignore_safe_or_broken_settings(tmp_path: Path):
    home, project = tmp_path / "home", tmp_path / "work"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"defaultMode": "default"}}))
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text("{not json")
    assert checks.check_permissions(home, project).ok


def test_workspace(tmp_path: Path):
    assert checks.check_workspace(tmp_path).ok
    assert not checks.check_workspace(tmp_path / "missing").ok


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/local/bin/claude")


def test_claude_auth_logged_out(fake_claude):
    runner = lambda *a, **k: completed(json.dumps({"loggedIn": False, "authMethod": "none"}), returncode=1)
    result = checks.check_claude_auth(runner)
    assert not result.ok
    assert "login" in result.fix


def test_claude_auth_subscription(fake_claude):
    runner = lambda *a, **k: completed(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}))
    result = checks.check_claude_auth(runner)
    assert result.ok
    assert "max" in result.detail


def test_claude_auth_unreadable_output(fake_claude):
    assert not checks.check_claude_auth(lambda *a, **k: completed("oops")).ok


def test_claude_auth_timeout(fake_claude):
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=15)

    assert not checks.check_claude_auth(runner).ok


def test_claude_cli_missing(monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    assert not checks.check_claude_auth().ok
