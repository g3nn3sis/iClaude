"""Replace Claude Code's raw usage-limit error with a short "Usage reached" reply."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

LIMIT_TEXT = re.compile(r"usage limit reached|hit your (?:usage |session |weekly )?limit", re.IGNORECASE)
RESET_EPOCH = re.compile(r"limit reached\|(\d{9,11})", re.IGNORECASE)


def limit_signal(message: Any) -> tuple[bool, int | None]:
    """Return (hit, resets_at) for one SDK message."""
    info = getattr(message, "rate_limit_info", None)
    if info is not None:
        blocked = info.status == "rejected" and info.overage_status not in ("allowed", "allowed_warning")
        return blocked, info.resets_at
    if getattr(message, "error", None) == "rate_limit":
        return True, None
    result = getattr(message, "result", None)
    if getattr(message, "is_error", False) and isinstance(result, str) and LIMIT_TEXT.search(result):
        match = RESET_EPOCH.search(result)
        return True, int(match.group(1)) if match else None
    return False, None


def notice(resets_at: int | None, tz: str | None = None) -> str:
    if not resets_at:
        return "Usage reached."
    try:
        zone = ZoneInfo(tz or os.environ.get("TZ") or "UTC")
    except (KeyError, ValueError):
        zone = timezone.utc
    when = datetime.fromtimestamp(resets_at, tz=timezone.utc).astimezone(zone)
    today = datetime.now(zone).date()
    stamp = when.strftime("%H:%M") if when.date() == today else when.strftime("%a %d %b %H:%M")
    return f"Usage reached. Claude is available again at {stamp} ({when.tzname()})."


class LimitTracker:
    """Collects limit signals across one response stream and rewrites what the user would see."""

    def __init__(self) -> None:
        self.hit = False
        self.resets_at: int | None = None

    def observe(self, message: Any) -> Any:
        hit, resets_at = limit_signal(message)
        if resets_at:
            self.resets_at = resets_at
        if hit:
            self.hit = True
        if not self.hit:
            return message
        text = notice(self.resets_at)
        if hasattr(message, "result") and getattr(message, "is_error", False):
            message.result = text
        elif getattr(message, "error", None) == "rate_limit" and hasattr(message, "content"):
            from claude_agent_sdk import TextBlock

            message.content = [TextBlock(text=text)]
        return message


def install() -> None:
    """Wrap ClaudeSDKClient.receive_response so every bridge session gets the short notice."""
    from claude_agent_sdk import ClaudeSDKClient

    original = ClaudeSDKClient.receive_response
    if getattr(original, "_iclaude_usage", False):
        return

    async def receive_response(self):
        tracker = LimitTracker()
        async for message in original(self):
            yield tracker.observe(message)

    receive_response._iclaude_usage = True
    ClaudeSDKClient.receive_response = receive_response
