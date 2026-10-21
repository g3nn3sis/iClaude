"""Report which MCP connectors a bridged Claude session can actually reach."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass

from .checks import check_claude_auth

EXPECTED = ("GitHub", "Fastmail", "Vercel", "Cloudflare")
SETTLE_SECONDS = 45


@dataclass(frozen=True)
class Connector:
    name: str
    status: str
    scope: str = ""
    tools: int = 0
    error: str = ""


def parse_status(response: dict) -> list[Connector]:
    return [
        Connector(
            name=str(server.get("name", "")),
            status=str(server.get("status", "unknown")),
            scope=str(server.get("scope") or ""),
            tools=len(server.get("tools") or []),
            error=str(server.get("error") or ""),
        )
        for server in response.get("mcpServers") or []
    ]


def match_expected(connectors: list[Connector], expected=EXPECTED) -> dict[str, Connector | None]:
    """Map each expected service to the connector whose name mentions it."""
    found: dict[str, Connector | None] = {}
    for service in expected:
        matches = [c for c in connectors if service.lower() in c.name.lower()]
        matches.sort(key=lambda c: c.status != "connected")
        found[service] = matches[0] if matches else None
    return found


async def fetch_status(project_dir: str, timeout: float = SETTLE_SECONDS) -> dict:
    """Open a session with the bridge's settings sources and read MCP status, without a model turn."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    options = ClaudeAgentOptions(
        cwd=project_dir,
        setting_sources=["user", "project"],
        system_prompt={"type": "preset", "preset": "claude_code"},
    )
    async with ClaudeSDKClient(options=options) as client:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            response = await client.get_mcp_status()
            pending = [s for s in response.get("mcpServers") or [] if s.get("status") == "pending"]
            if not pending or asyncio.get_running_loop().time() >= deadline:
                return response
            await asyncio.sleep(2)


def gh_status() -> str:
    try:
        result = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "gh CLI unavailable"
    return "gh CLI logged in" if result.returncode == 0 else "gh CLI not logged in (optional: ./iclaude shell, then gh auth login)"


def report(project_dir: str | None = None) -> int:
    project_dir = project_dir or os.environ.get("CLAUDE_PROJECT_DIR", "/workspace")
    auth = check_claude_auth()
    if not auth.ok:
        print(f"  ✗ Claude login: {auth.detail}. Connectors come from your Claude account. {auth.fix}")
        return 1
    print("Opening a Claude session with the bridge's settings (no message is sent to the model)...", flush=True)
    try:
        connectors = parse_status(asyncio.run(fetch_status(project_dir)))
    except Exception as exc:
        print(f"  ✗ Could not start a Claude session: {exc}")
        print("    Check ./iclaude check claude, then retry.")
        return 1

    print("\nExpected connectors:")
    for service, connector in match_expected(connectors).items():
        if connector is None:
            print(f"  - {service}: not available. Connect it at claude.ai > Settings > Connectors, then rerun.")
        elif connector.status == "connected":
            print(f"  ✓ {service}: connected as '{connector.name}' ({connector.tools} tools)")
        elif connector.status == "needs-auth":
            print(f"  ! {service}: '{connector.name}' needs authorisation at claude.ai > Settings > Connectors")
        else:
            print(f"  ✗ {service}: '{connector.name}' is {connector.status} {connector.error}".rstrip())
    others = [c for c in connectors if c not in match_expected(connectors).values()]
    if others:
        print("\nOther MCP servers:")
        for c in others:
            print(f"  · {c.name}: {c.status}{f' ({c.scope})' if c.scope else ''}")
    print(f"\nGitHub CLI: {gh_status()}")
    print("The bridge adds its own Inkbox tools on top of these when it runs.")
    return 0
