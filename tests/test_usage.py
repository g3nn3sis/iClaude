import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from iclaude_runtime import usage


def event(status, resets_at=1_900_000_000, overage=None):
    return SimpleNamespace(rate_limit_info=SimpleNamespace(status=status, resets_at=resets_at, overage_status=overage))


def result(text, is_error=True):
    return SimpleNamespace(result=text, is_error=is_error)


def test_limit_signal_sources():
    assert usage.limit_signal(event("rejected")) == (True, 1_900_000_000)
    assert usage.limit_signal(event("allowed_warning")) == (False, 1_900_000_000)
    assert usage.limit_signal(event("rejected", overage="allowed"))[0] is False
    assert usage.limit_signal(SimpleNamespace(error="rate_limit")) == (True, None)
    assert usage.limit_signal(result("Claude AI usage limit reached|1900000000")) == (True, 1_900_000_000)
    assert usage.limit_signal(result("You've hit your limit · resets 5pm")) == (True, None)
    assert usage.limit_signal(result("You've hit your limit", is_error=False)) == (False, None)
    assert usage.limit_signal(result("Some other failure")) == (False, None)


def test_notice_formats_reset_time():
    assert usage.notice(None) == "Usage reached."
    soon = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())
    text = usage.notice(soon, "UTC")
    assert text.startswith("Usage reached. Claude is available again at ") and text.endswith("(UTC).")


def test_tracker_rewrites_error_result_only():
    tracker = usage.LimitTracker()
    tracker.observe(event("rejected"))
    ok = tracker.observe(result("fine", is_error=False))
    assert ok.result == "fine"
    failed = tracker.observe(result("You've hit your limit · resets 5pm"))
    assert failed.result.startswith("Usage reached.")


def test_tracker_leaves_normal_turns_alone():
    tracker = usage.LimitTracker()
    message = tracker.observe(result("API Error: 500"))
    assert message.result == "API Error: 500"


def test_install_wraps_receive_response():
    sdk = pytest.importorskip("claude_agent_sdk")
    original = sdk.ClaudeSDKClient.receive_response

    async def fake(self):
        yield sdk.AssistantMessage(content=[sdk.TextBlock(text="You've hit your limit")], model="m", error="rate_limit")
        yield sdk.ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1,
                                session_id="s", result="You've hit your limit · resets 5pm")

    sdk.ClaudeSDKClient.receive_response = fake
    try:
        usage.install()
        usage.install()

        async def collect():
            return [m async for m in sdk.ClaudeSDKClient.receive_response(None)]

        assistant, final = asyncio.run(collect())
        assert assistant.content[0].text == "Usage reached."
        assert final.result == "Usage reached."
    finally:
        sdk.ClaudeSDKClient.receive_response = original
