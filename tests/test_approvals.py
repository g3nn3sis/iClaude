import json

import pytest

from iclaude_runtime import approvals, checks, cli


@pytest.mark.parametrize(
    "tool, category",
    [
        ("mcp__claude_ai_Fastmail__create_event", "calendar"),
        ("mcp__claude_ai_Fastmail__update_event", "calendar"),
        ("mcp__claude_ai_Fastmail__rsvp_event", "calendar"),
        ("mcp__claude_ai_Fastmail__send_email", "email"),
        ("mcp__claude_ai_Fastmail__draft_email", "email"),
        ("mcp__inkbox__inkbox_send_email", "email"),
        ("mcp__claude_ai_Inkbox__inkbox_email_forward", "email"),
        ("mcp__claude_ai_Vercel__create_deployment", "deploy"),
        ("mcp__claude_ai_Vercel__request_promote", "deploy"),
        ("mcp__claude_ai_Fastmail__delete_event", "delete"),
        ("mcp__claude_ai_Neon__delete_project", "delete"),
        ("mcp__claude_ai_Vercel__buy_domain", "pay"),
        ("mcp__claude_ai_Fastmail__read_email", None),
        ("mcp__claude_ai_Fastmail__search_events", None),
        ("mcp__claude_ai_Vercel__get_deployment", None),
        ("mcp__claude_ai_Vercel__list_deployments", None),
        ("mcp__claude_ai_Vercel__get_domain_order", None),
        ("mcp__inkbox__inkbox_send_imessage", None),
        ("mcp__iclaude__cancel_reminder", None),
        ("Bash", None),
        ("Write", None),
        ("Edit", None),
    ],
)
def test_categorise(tool, category):
    assert approvals.categorise(tool) == category


def test_parse_orders_expands_all_and_reports_unknown():
    assert approvals.parse("email, calendar") == (["calendar", "email"], [])
    assert approvals.parse("all")[0] == [c.name for c in approvals.CATEGORIES]
    assert approvals.parse("none") == ([], [])
    assert approvals.parse("calender") == ([], ["calender"])
    assert approvals.parse(None) == ([], [])


def test_auto_approves_only_enabled_categories():
    env = {approvals.SETTING: "calendar"}
    assert approvals.auto_approves("mcp__claude_ai_Fastmail__create_event", env)
    assert not approvals.auto_approves("mcp__claude_ai_Fastmail__send_email", env)
    assert not approvals.auto_approves("mcp__claude_ai_Fastmail__delete_event", env)
    assert not approvals.auto_approves("Bash", {approvals.SETTING: "all"})


def test_prompt_text_lists_categories_and_keeps_injection_guard():
    assert approvals.prompt_text({}) == ""
    text = approvals.prompt_text({approvals.SETTING: "calendar,email"})
    assert "calendar events" in text and "send, reply to" in text
    assert "overrides" in text and "inside emails" in text
    assert "deploy" not in text


@pytest.fixture
def saved(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setenv("INKBOX_CLAUDE_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv(approvals.SETTING, raising=False)
    monkeypatch.setattr(cli, "_save", lambda name, value: store.__setitem__(name, value))
    return store


def test_approve_on_off_and_status(saved, monkeypatch, capsys):
    assert cli.cmd_approve("on", ["email", "calendar"]) == 0
    assert saved[approvals.SETTING] == "calendar,email"
    assert "malicious" in capsys.readouterr().out
    monkeypatch.setenv(approvals.SETTING, "calendar,email")
    assert cli.cmd_approve("off", ["email"]) == 0
    assert saved[approvals.SETTING] == "calendar"
    assert cli.cmd_approve("off", ["all"]) == 0
    assert saved[approvals.SETTING] == "none"
    capsys.readouterr()
    assert cli.cmd_approve("status", []) == 0
    out = capsys.readouterr().out
    assert "on   calendar" in out and "off  deploy" in out


def test_approve_rejects_unknown_without_saving(saved):
    assert cli.cmd_approve("on", ["calender"]) == 1
    assert cli.cmd_approve("on", []) == 1
    assert saved == {}


def test_preflight_shows_auto_approve_and_rejects_typos(tmp_path):
    home, project = tmp_path / "home", tmp_path / "work"
    result = checks.check_permissions(home, project, {approvals.SETTING: "calendar,email"})
    assert result.ok and "auto-approved: calendar, email" in result.detail
    assert not checks.check_permissions(home, project, {approvals.SETTING: "calender"}).ok


def test_auto_mode_round_trip_keeps_other_settings(tmp_path):
    path = approvals.user_settings_path(tmp_path)
    assert not approvals.auto_mode(tmp_path)
    path.parent.mkdir()
    path.write_text('{"model": "opus", "permissions": {"allow": ["Read"]}}')
    approvals.set_auto_mode(tmp_path, True)
    assert approvals.auto_mode(tmp_path)
    assert json.loads(path.read_text()) == {"model": "opus", "permissions": {"allow": ["Read"], "defaultMode": "auto"}}
    approvals.set_auto_mode(tmp_path, False)
    assert json.loads(path.read_text()) == {"model": "opus", "permissions": {"allow": ["Read"]}}
    path.write_text("{broken")
    with pytest.raises(ValueError):
        approvals.set_auto_mode(tmp_path, True)


def test_auto_mode_command_and_preflight(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("INKBOX_CLAUDE_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv(approvals.SETTING, raising=False)
    assert cli.cmd_auto_mode("on") == 0
    assert "auto mode is on" in capsys.readouterr().out
    result = checks.check_permissions(tmp_path, tmp_path / "work", {})
    assert result.ok and "auto mode" in result.detail
    assert cli.cmd_auto_mode("off") == 0
    assert not approvals.auto_mode(tmp_path)
