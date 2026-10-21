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


def reset_time(resets_at: int, tz: str | None = None) -> str:
    try:
        zone = ZoneInfo(tz or os.environ.get("TZ") or "UTC")
    except (KeyError, ValueError):
        zone = timezone.utc
    when = datetime.fromtimestamp(resets_at, tz=timezone.utc).astimezone(zone)
    today = datetime.now(zone).date()
    stamp = when.strftime("%H:%M") if when.date() == today else when.strftime("%a %d %b %H:%M")
    return f"{stamp} ({when.tzname()})"


def notice(resets_at: int | None, tz: str | None = None) -> str:
    if not resets_at:
        return "Usage reached."
    return f"Usage reached. Claude is available again at {reset_time(resets_at, tz)}."


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


WARN_WINDOWS = (("five_hour", "5-hour"), ("seven_day", "weekly"))


def warnings(data: dict, threshold: float, warned: set[str], tz: str | None = None) -> list[tuple[str, str]]:
    """Return (key, text) for each usage window that crossed the threshold and was not warned about."""
    out = []
    for name, label in WARN_WINDOWS:
        block = data.get(name)
        if not isinstance(block, dict) or block.get("utilization") is None:
            continue
        used = float(block["utilization"])
        reset = _reset_epoch(block.get("resets_at"))
        key = f"{name}:{reset // 3600 if reset else block.get('resets_at')}"
        if used < threshold or key in warned:
            continue
        out.append((key, f"Heads-up: you've used {round(used)}% of your {label} Claude limit"
                         + (f". It resets at {reset_time(reset, tz)}." if reset else ".")))
    return out


def _reset_epoch(value) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None
