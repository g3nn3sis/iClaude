"""Text like a person: a heads-up when work starts, a few updates, then the result in short bubbles.

The bridge sends a whole turn as one message. In the "natural" style (the default) iClaude
sends the text Claude writes before a tool call straight away, throttled so it never turns
into play-by-play, and splits the final reply into one text per paragraph.
"""

from __future__ import annotations

import re
import time
from typing import Mapping

SETTING = "ICLAUDE_REPLY_STYLE"
STYLES = ("natural", "single")
TEXT_MODES = ("imessage", "sms")
UPDATE_GAP_SECONDS = 20.0
MAX_UPDATES = 4
MAX_BUBBLES = 4
BUBBLE_PAUSE_SECONDS = 0.8

PROMPT = """## Texting rhythm
On iMessage and SMS, text like a person rather than sending one long report:
- If a request needs tools and will take more than a few seconds, write a short heads-up before your first tool call, such as "On it, checking your calendar". Skip it for quick answers.
- While working, write a one-line update only at a real milestone or when the plan changes ("Found it, the build was missing a key"). Text you write before a tool call is sent right away, at most one every 20 seconds, so do not narrate every step.
- Finish with the result as its own message. Put separate thoughts in separate short paragraphs; each paragraph arrives as its own text, so keep it to a few.
This replaces the earlier guidance to only text the result and not narrate, for iMessage and SMS."""


def style(env: Mapping[str, str]) -> str:
    value = (env.get(SETTING) or "natural").strip().lower()
    return value if value in STYLES else "natural"


def applies(mode: str, meta: Mapping | None) -> bool:
    """Only one-to-one texts with a person; email, Slack, voice, groups and companions keep one reply."""
    meta = meta or {}
    return (mode in TEXT_MODES and not meta.get("companion")
            and meta.get("conversation_kind", "direct") == "direct")


class Updates:
    """Per-turn throttle for progress texts: the first one always goes, then at most one per gap."""

    def __init__(self, clock=time.monotonic, gap: float = UPDATE_GAP_SECONDS, limit: int = MAX_UPDATES):
        self.clock, self.gap, self.limit = clock, gap, limit
        self.sent: list[str] = []
        self._last: float | None = None

    def take(self, text: str) -> str | None:
        text = text.strip()
        if not text or text == "[SILENT]" or len(self.sent) >= self.limit:
            return None
        now = self.clock()
        if self._last is not None and now - self._last < self.gap:
            return None
        self._last = now
        self.sent.append(text)
        return text


def _paragraphs(text: str) -> list[str]:
    parts, current, fenced = [], [], False
    for line in text.strip().splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
        if not line.strip() and not fenced:
            if current:
                parts.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        parts.append("\n".join(current).strip())
    return [p for p in parts if p]


def bubbles(reply: str, already_sent: list[str] = (), limit: int = MAX_BUBBLES) -> list[str]:
    """Split a reply into a few texts, dropping paragraphs that already went out as updates."""
    sent = {re.sub(r"\s+", " ", s).strip() for s in already_sent}
    parts = [p for p in _paragraphs(reply) if re.sub(r"\s+", " ", p) not in sent]
    while len(parts) > limit:
        i = min(range(len(parts) - 1), key=lambda k: len(parts[k]) + len(parts[k + 1]))
        parts[i:i + 2] = [parts[i] + "\n\n" + parts[i + 1]]
    return parts
