import asyncio
from types import SimpleNamespace

import pytest

from iclaude_runtime import hooks, notify


def test_remember_chat_and_add_context(tmp_path, monkeypatch):
    path = tmp_path / "chats.json"
    monkeypatch.setattr(hooks, "CHATS_FILE", path)
    hooks.remember_chat("+15551234567", "contact-1")
    assert hooks.load_chats() == {"+15551234567": "contact-1"}
    assert path.parent.stat().st_mode & 0o777 == 0o700

    buffered = []
    session = SimpleNamespace(buffer_context=lambda text, key: buffered.append((text, key)))
    manager = SimpleNamespace(get=lambda chat_id: session if chat_id == "contact-1" else None)

    async def run():
        monkeypatch.setitem(hooks._bridge, "loop", asyncio.get_running_loop())
        monkeypatch.setitem(hooks._bridge, "manager", manager)
        assert hooks.add_context("+15551234567", "note", "k")
        assert not hooks.add_context("+15550000000", "note", "k")
        await asyncio.sleep(0)

    asyncio.run(run())
    assert buffered == [("note", "k")]


def test_add_context_without_a_running_bridge(monkeypatch):
    monkeypatch.setitem(hooks._bridge, "loop", None)
    assert not hooks.add_context("+15551234567", "note", "k")


def test_notifier_refuses_unauthorised_numbers():
    notifier = notify.Notifier({"INKBOX_ALLOWED_USERS": "+15551234567,me@icloud.com"})
    with pytest.raises(PermissionError):
        notifier.send("+15550000000", "hi", "k")
    with pytest.raises(PermissionError):
        notifier.send("me@icloud.com", "hi", "k")


def test_notifier_sends_and_mirrors_into_the_conversation(monkeypatch):
    sent, mirrored = [], []
    notifier = notify.Notifier({"INKBOX_ALLOWED_USERS": "+15551234567"})
    notifier._identity = SimpleNamespace(send_imessage=lambda **kw: sent.append(kw))
    monkeypatch.setattr(hooks, "add_context", lambda contact, text, key: mirrored.append((contact, text, key)))
    notifier.send("+15551234567", "Reminder: x", "key1", "Reminder: x (ref 1)")
    assert sent == [{"to": "+15551234567", "text": "Reminder: x", "idempotency_key": "key1"}]
    assert mirrored[0][0] == "+15551234567" and mirrored[0][1].endswith("Reminder: x (ref 1)")
    assert "not their message" in mirrored[0][1]


def test_owner_rules():
    assert notify.owner({"INKBOX_ALLOWED_USERS": "+15551234567"}) == ("+15551234567", "")
    assert "not an authorised" in notify.owner({"INKBOX_ALLOWED_USERS": "+15551234567", "ICLAUDE_ALERT_TO": "+15550000000"})[1]


def test_install_injects_tools_only_into_bridge_sessions(monkeypatch):
    sdk = pytest.importorskip("claude_agent_sdk")
    pytest.importorskip("inkbox_claude.sessions")
    from inkbox_claude.tools import CURRENT_SESSION

    hooks.install(lambda: ({"type": "sdk", "name": "iclaude", "instance": None}, ["remind"]))
    hooks.install(lambda: ({}, []))
    bridge_options = sdk.ClaudeAgentOptions(mcp_servers={"inkbox": {"type": "sdk", "name": "inkbox", "instance": None}},
                                            allowed_tools=["Read"])
    token = CURRENT_SESSION.set(SimpleNamespace(reply_meta={}))
    try:
        client = sdk.ClaudeSDKClient(options=bridge_options)
        other = sdk.ClaudeSDKClient(options=sdk.ClaudeAgentOptions(mcp_servers={}))
    finally:
        CURRENT_SESSION.reset(token)
    assert set(client.options.mcp_servers) == {"inkbox", "iclaude"}
    assert client.options.allowed_tools == ["Read", "mcp__iclaude__remind"]
    assert other.options.mcp_servers == {}
    outside = sdk.ClaudeSDKClient(options=bridge_options)
    assert set(outside.options.mcp_servers) == {"inkbox"}



def test_install_auto_approves_enabled_categories_and_tells_claude():
    sdk = pytest.importorskip("claude_agent_sdk")
    sessions = pytest.importorskip("inkbox_claude.sessions")
    from inkbox_claude.tools import CURRENT_SESSION

    hooks.install(None, lambda: {"ICLAUDE_AUTO_APPROVE": "calendar"})

    async def escalate(*args, **kwargs):
        return "3"

    session = SimpleNamespace(reply_meta={}, _current_turn=SimpleNamespace(execution_observed=False),
                              always_allowed=set(), companion_approver="", _escalate=escalate)

    def decide(tool, meta=None):
        session.reply_meta = meta or {}
        return asyncio.run(sessions.ContactSession._can_use_tool(session, tool, {}, None))

    assert isinstance(decide("mcp__claude_ai_Fastmail__create_event"), sdk.PermissionResultAllow)
    assert session._current_turn.execution_observed
    assert isinstance(decide("mcp__claude_ai_Fastmail__send_email"), sdk.PermissionResultDeny)
    assert isinstance(decide("Bash"), sdk.PermissionResultDeny)
    assert isinstance(decide("mcp__claude_ai_Fastmail__create_event", {"companion": True}), sdk.PermissionResultDeny)

    options = sdk.ClaudeAgentOptions(mcp_servers={"inkbox": {"type": "sdk", "name": "inkbox", "instance": None}},
                                     system_prompt={"type": "preset", "preset": "claude_code", "append": "bridge"})
    token = CURRENT_SESSION.set(SimpleNamespace(reply_meta={}))
    try:
        client = sdk.ClaudeSDKClient(options=options)
    finally:
        CURRENT_SESSION.reset(token)
    assert client.options.system_prompt["append"].startswith("bridge\n\n## Auto-approved actions")
