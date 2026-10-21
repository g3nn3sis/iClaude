"""Guards the upstream bridge internals iClaude relies on. Runs inside the image."""

import pytest

setup_wizard = pytest.importorskip("inkbox_claude.setup_wizard")


@pytest.mark.parametrize(
    "name",
    ["interactive_setup", "_configure_autostart", "_configure_project_dir", "_save",
     "prompt", "print_info", "print_error", "print_success", "color", "Colors"],
)
def test_setup_wizard_hooks_exist(name):
    assert hasattr(setup_wizard, name)


def test_save_writes_private_env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setenv("INKBOX_CLAUDE_ENV_FILE", str(path))
    setup_wizard._save("INKBOX_ALLOWED_USERS", "+15551234567")
    assert "INKBOX_ALLOWED_USERS=+15551234567" in path.read_text()
    assert path.stat().st_mode & 0o077 == 0


def test_bridge_honours_allowlist():
    from inkbox_claude.config import read_config
    from inkbox_claude.gateway import InkboxGateway

    gateway = InkboxGateway.__new__(InkboxGateway)
    gateway.cfg = read_config()
    gateway.cfg.allowed_users = ["+15551234567"]
    gateway.cfg.allow_all_users = False
    assert gateway._sender_allowed("+15551234567")
    assert not gateway._sender_allowed("+15550000000")


def test_sessions_stream_through_receive_response():
    import inspect

    from inkbox_claude import sessions

    source = inspect.getsource(sessions)
    assert "ClaudeSDKClient(options=options)" in source and "client.receive_response()" in source


def test_bridge_cli_runs_in_foreground():
    import inspect

    from inkbox_claude import cli

    assert '"run"' in inspect.getsource(cli.main) and "run_foreground" in inspect.getsource(cli.main)


@pytest.mark.parametrize("name", ["iter_emails", "get_message", "send_imessage", "mailbox"])
def test_identity_api_used_by_alerts(name):
    from inkbox.agent_identity import AgentIdentity

    assert hasattr(AgentIdentity, name)


def test_sdk_options_used_by_alerts():
    import dataclasses

    from claude_agent_sdk import ClaudeAgentOptions

    fields = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    assert {"tools", "strict_mcp_config", "setting_sources", "can_use_tool", "max_turns", "env"} <= fields


def test_session_internals_used_by_hooks():
    import inspect

    from inkbox_claude import gateway, sessions, tools

    assert hasattr(tools, "CURRENT_SESSION")
    assert "CURRENT_SESSION.set(self)" in inspect.getsource(sessions.ContactSession._ensure_client)
    assert list(inspect.signature(sessions.ContactSession.handle_inbound).parameters) == ["self", "text", "mode", "meta"]
    assert list(inspect.signature(sessions.ContactSession.buffer_context).parameters)[:3] == ["self", "text", "source_id"]
    assert "Earlier group messages are context" in inspect.getsource(sessions.ContactSession._run_turn)
    assert "self.sessions = SessionManager(" in inspect.getsource(gateway.InkboxGateway.run)
    assert '"sender": sender' in inspect.getsource(gateway.InkboxGateway._on_imessage_received_once)


def test_usage_and_voice_helpers_exist():
    from inkbox_claude import claude_usage, config, setup_wizard

    assert callable(claude_usage.fetch_usage)
    assert {s.value for s in config.VoiceStack} >= {"openai_realtime", "inkbox_tts_stt"}
    assert callable(setup_wizard._save_voice_stack)
