import pytest

from iclaude_runtime import cli
from iclaude_runtime.checks import Check

PASS = [Check("a", True, "ok")]
FAIL = [Check("a", False, "missing", "fix it")]


def test_run_waits_for_preflight_then_execs_bridge(monkeypatch):
    results = iter([FAIL, FAIL, PASS])
    sleeps, execs = [], []
    monkeypatch.setattr(cli, "preflight", lambda: next(results))
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)
    monkeypatch.setattr(cli, "seed_claude_md", lambda home: False)
    monkeypatch.setattr(cli, "memory_environment", lambda env: "on")
    monkeypatch.setattr(cli.os, "execv", lambda file, args: execs.append(args[1:]))
    cli.cmd_run()
    assert sleeps == [cli.WAIT_SECONDS, cli.WAIT_SECONDS]
    assert execs == [["-m", "iclaude_runtime.bridge"]]


def test_run_logs_unchanged_failures_once(monkeypatch, capsys):
    results = iter([FAIL, FAIL, FAIL, PASS])
    monkeypatch.setattr(cli, "preflight", lambda: next(results))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli, "seed_claude_md", lambda home: False)
    monkeypatch.setattr(cli, "memory_environment", lambda env: "on")
    monkeypatch.setattr(cli.os, "execv", lambda file, args: None)
    cli.cmd_run()
    assert capsys.readouterr().out.count("waiting for setup") == 1


@pytest.fixture
def saved(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setenv("INKBOX_CLAUDE_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("INKBOX_ALLOWED_USERS", raising=False)
    monkeypatch.setattr(cli, "_save", lambda name, value: store.__setitem__(name, value))
    return store


def test_allow_adds_and_forces_allowlist_mode(saved):
    assert cli.cmd_allow(["+1 555 123 4567"], replace=False, remove=False) == 0
    assert saved == {"INKBOX_ALLOWED_USERS": "+15551234567", "INKBOX_ALLOW_ALL_USERS": "false"}


def test_allow_merges_remove_and_replace(saved, monkeypatch):
    monkeypatch.setenv("INKBOX_ALLOWED_USERS", "+15551234567,a@b.co")
    cli.cmd_allow(["c@d.co"], replace=False, remove=False)
    assert saved["INKBOX_ALLOWED_USERS"] == "+15551234567,a@b.co,c@d.co"
    cli.cmd_allow(["a@b.co"], replace=False, remove=True)
    assert saved["INKBOX_ALLOWED_USERS"] == "+15551234567"
    cli.cmd_allow(["x@y.co"], replace=True, remove=False)
    assert saved["INKBOX_ALLOWED_USERS"] == "x@y.co"


def test_allow_rejects_invalid_without_saving(saved):
    assert cli.cmd_allow(["bob"], replace=False, remove=False) == 1
    assert saved == {}


def test_healthcheck(monkeypatch):
    monkeypatch.setattr(cli, "_probe", lambda path: {"ready": True})
    assert cli.cmd_healthcheck() == 0
    monkeypatch.setattr(cli, "_probe", lambda path: {"ready": False})
    assert cli.cmd_healthcheck() == 1
    monkeypatch.setattr(cli, "_probe", lambda path: None)
    assert cli.cmd_healthcheck() == 1


def test_select_checks_by_prefix():
    checks = [Check("Claude login", True, ""), Check("Inkbox identity", False, ""), Check("Workspace", True, "")]
    assert [c.name for c in cli.select_checks(checks, ["claude"])] == ["Claude login"]
    assert [c.name for c in cli.select_checks(checks, ["INKBOX", "work"])] == ["Inkbox identity", "Workspace"]
    assert cli.select_checks(checks, []) == checks
