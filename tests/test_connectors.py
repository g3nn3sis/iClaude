from iclaude_runtime.connectors import Connector, match_expected, parse_status


def test_parse_status():
    response = {"mcpServers": [
        {"name": "claude.ai GitHub", "status": "connected", "scope": "claudeai", "tools": [{"name": "a"}, {"name": "b"}]},
        {"name": "claude.ai Vercel", "status": "needs-auth", "scope": "claudeai"},
        {"name": "local", "status": "failed", "error": "boom"},
    ]}
    assert parse_status(response) == [
        Connector("claude.ai GitHub", "connected", "claudeai", 2),
        Connector("claude.ai Vercel", "needs-auth", "claudeai"),
        Connector("local", "failed", "", 0, "boom"),
    ]
    assert parse_status({}) == []


def test_match_expected_prefers_connected():
    connectors = [
        Connector("claude.ai Fastmail (old)", "failed"),
        Connector("claude.ai Fastmail", "connected"),
        Connector("claude.ai Cloudflare Developer Platform", "connected"),
    ]
    found = match_expected(connectors)
    assert found["Fastmail"].name == "claude.ai Fastmail"
    assert found["Cloudflare"].status == "connected"
    assert found["GitHub"] is None
    assert found["Vercel"] is None
