from pathlib import Path

from iclaude_runtime import defaults


def test_default_claude_md_ships_with_runtime():
    text = (defaults.DEFAULTS_DIR / "CLAUDE.md").read_text()
    assert "Confirm before acting" in text
    assert "never overwrites" in text


def test_seed_claude_md_installs_once(tmp_path: Path):
    assert defaults.seed_claude_md(tmp_path)
    target = tmp_path / ".claude" / "CLAUDE.md"
    assert target.read_text() == (defaults.DEFAULTS_DIR / "CLAUDE.md").read_text()
    target.write_text("mine")
    assert not defaults.seed_claude_md(tmp_path)
    assert target.read_text() == "mine"


def test_seed_claude_md_without_source(tmp_path: Path):
    assert not defaults.seed_claude_md(tmp_path, source=tmp_path / "missing.md")


def test_memory_stays_on_for_single_owner():
    env = {}
    note = defaults.memory_environment({"INKBOX_ALLOWED_USERS": "+15551234567"}, env)
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" not in env
    assert "single owner" in note


def test_memory_off_for_several_contacts():
    env = {}
    defaults.memory_environment({"INKBOX_ALLOWED_USERS": "+15551234567,a@b.co"}, env)
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


def test_shared_memory_opt_in():
    env = {}
    note = defaults.memory_environment({"INKBOX_ALLOWED_USERS": "+15551234567,a@b.co", "ICLAUDE_SHARED_MEMORY": "true"}, env)
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" not in env
    assert "shared" in note
