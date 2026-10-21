import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from iclaude_runtime import watchers

SINCE = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(routes, calls):
    def opener(request, timeout):
        calls.append((request.full_url, request.headers.get("Authorization")))
        for prefix, payload in routes:
            if request.full_url.startswith(prefix):
                return Response(json.dumps(payload).encode())
        raise AssertionError(request.full_url)
    return opener


def test_github_keeps_actionable_reasons():
    payload = [
        {"id": "1", "reason": "review_requested", "updated_at": "2026-10-23T12:05:00Z",
         "subject": {"title": "Fix login", "url": "https://api.github.com/repos/o/r/pulls/12"}, "repository": {"full_name": "o/r"}},
        {"id": "2", "reason": "subscribed", "updated_at": "2026-10-23T12:06:00Z", "subject": {}, "repository": {}},
        {"id": "3", "reason": "mention", "updated_at": "2026-10-23T11:00:00Z", "subject": {}, "repository": {}},
    ]
    seen = []

    def runner(cmd, **kwargs):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))

    notices = watchers.GitHub(runner).fetch(SINCE)
    assert [n.line for n in notices] == ["review requested: o/r#12 Fix login"]
    assert seen[0][-1] == "since=2026-10-23T12:00:00Z"
    with pytest.raises(RuntimeError):
        watchers.GitHub(lambda cmd, **k: SimpleNamespace(returncode=1, stdout="")).fetch(SINCE)


def test_vercel_reports_failed_deploys_since_cursor():
    calls = []
    deploys = {"deployments": [
        {"uid": "d1", "name": "site", "target": "production", "createdAt": int((SINCE + timedelta(minutes=1)).timestamp() * 1000),
         "meta": {"githubCommitMessage": "Bump deps"}},
        {"uid": "d0", "name": "site", "createdAt": int((SINCE - timedelta(minutes=1)).timestamp() * 1000)},
    ]}
    source = watchers.Vercel("tok", "team_1", opener_for([("https://api.vercel.com/v6/deployments", deploys)], calls))
    [notice] = source.fetch(SINCE)
    assert notice.line == "site production deploy failed: Bump deps"
    assert "state=ERROR" in calls[0][0] and "teamId=team_1" in calls[0][0] and calls[0][1] == "Bearer tok"


def test_cloudflare_reports_failed_pages_deploys():
    calls = []
    base = "https://api.cloudflare.com/client/v4/accounts/acc/pages/projects"
    routes = [
        (f"{base}/blog/deployments", {"result": [
            {"id": "x", "environment": "production", "created_on": "2026-10-23T12:10:00Z",
             "latest_stage": {"name": "build", "status": "failure"},
             "deployment_trigger": {"metadata": {"commit_message": "New post"}}},
            {"id": "y", "created_on": "2026-10-23T12:11:00Z", "latest_stage": {"status": "success"}},
        ]}),
        (base, {"success": True, "result": [{"name": "blog"}]}),
    ]
    [notice] = watchers.CloudflarePages("tok", "acc", opener_for(routes, calls)).fetch(SINCE)
    assert notice.line == "blog production deploy failed at build: New post"


def test_format_notices_caps_the_list():
    notices = [watchers.Notice(str(i), SINCE, f"item {i}") for i in range(20)]
    text = watchers.format_notices("GitHub", notices)
    assert text.startswith("GitHub: 20 updates") and text.endswith("and 5 more")
