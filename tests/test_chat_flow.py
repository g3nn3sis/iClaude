import pytest

from iclaude_runtime import chat_flow, cli


def test_style_defaults_to_natural():
    assert chat_flow.style({}) == "natural"
    assert chat_flow.style({chat_flow.SETTING: "single"}) == "single"
    assert chat_flow.style({chat_flow.SETTING: "bogus"}) == "natural"


@pytest.mark.parametrize(
    "mode, meta, expected",
    [
        ("imessage", {}, True),
        ("sms", {"conversation_kind": "direct"}, True),
        ("imessage", {"conversation_kind": "group"}, False),
        ("imessage", {"companion": True}, False),
        ("email", {}, False),
        ("slack", {}, False),
        ("voice", {}, False),
    ],
)
def test_applies_only_to_direct_texts(mode, meta, expected):
    assert chat_flow.applies(mode, meta) is expected


def test_updates_throttle():
    now = [0.0]
    updates = chat_flow.Updates(clock=lambda: now[0], gap=20, limit=3)
    assert updates.take("On it") == "On it"
    now[0] = 5
    assert updates.take("Reading the file") is None
    now[0] = 30
    assert updates.take("  Found it  ") == "Found it"
    assert updates.take("") is None and updates.take("[SILENT]") is None
    now[0] = 60
    assert updates.take("Testing") == "Testing"
    now[0] = 100
    assert updates.take("Too many") is None
    assert updates.sent == ["On it", "Found it", "Testing"]


def test_bubbles_split_paragraphs_and_skip_sent_updates():
    reply = "On it, checking.\n\nAdded lunch with Sam at 1pm.\n\n\nAnything else?"
    assert chat_flow.bubbles(reply, ["On it,   checking."]) == ["Added lunch with Sam at 1pm.", "Anything else?"]
    assert chat_flow.bubbles("Done.") == ["Done."]
    assert chat_flow.bubbles("On it", ["On it"]) == []


def test_bubbles_keep_code_blocks_whole_and_cap_count():
    reply = "Here:\n\n```\na = 1\n\nb = 2\n```\n\nThat's it."
    assert chat_flow.bubbles(reply) == ["Here:", "```\na = 1\n\nb = 2\n```", "That's it."]
    many = "\n\n".join(f"p{i}" for i in range(7))
    parts = chat_flow.bubbles(many, limit=4)
    assert len(parts) == 4 and "\n\n".join(parts) == many


def test_replies_command(monkeypatch, tmp_path, capsys):
    store = {}
    monkeypatch.setenv("INKBOX_CLAUDE_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv(chat_flow.SETTING, raising=False)
    monkeypatch.setattr(cli, "_save", lambda name, value: store.__setitem__(name, value))
    assert cli.cmd_replies(None) == 0
    assert "Replies: natural" in capsys.readouterr().out and store == {}
    assert cli.cmd_replies("single") == 0
    assert store == {chat_flow.SETTING: "single"} and "Replies: single" in capsys.readouterr().out
