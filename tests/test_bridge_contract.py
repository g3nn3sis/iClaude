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
