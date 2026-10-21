"""Rule-based alerts from GitHub, Vercel and Cloudflare Pages. Plain API polling, no Claude usage."""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

GITHUB_REASONS = {
    "review_requested": "review requested",
    "mention": "you were mentioned",
    "team_mention": "your team was mentioned",
    "assign": "assigned to you",
    "author": "activity on your thread",
    "comment": "new comment",
    "ci_activity": "CI run finished",
    "security_alert": "security alert",
}


@dataclass
class Notice:
    key: str
    when: datetime
    line: str


def _parse(value: str | int | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _short(text: str, limit: int = 90) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _get_json(url: str, token: str, opener: Callable) -> dict | list:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with opener(request, timeout=20) as response:
        return json.loads(response.read())


class GitHub:
    name = "GitHub"

    def __init__(self, runner: Callable = subprocess.run):
        self.runner = runner

    def fetch(self, since: datetime) -> list[Notice]:
        stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = self.runner(["gh", "api", "-X", "GET", "notifications", "-f", f"since={stamp}"],
                             capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError("gh api notifications failed (is gh logged in?)")
        notices = []
        for item in json.loads(result.stdout or "[]"):
            reason = item.get("reason")
            when = _parse(item.get("updated_at"))
            if reason not in GITHUB_REASONS or when is None or when <= since:
                continue
            subject = item.get("subject") or {}
            number = str(subject.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
            ref = item.get("repository", {}).get("full_name", "")
            if number.isdigit():
                ref += f"#{number}"
            notices.append(Notice(f"github:{item.get('id')}:{item.get('updated_at')}", when,
                                  f"{GITHUB_REASONS[reason]}: {ref} {_short(subject.get('title'))}"))
        return notices


class Vercel:
    name = "Vercel"
    API = "https://api.vercel.com/v6/deployments"

    def __init__(self, token: str, team: str = "", opener: Callable = urllib.request.urlopen):
        self.token, self.team, self.opener = token, team, opener

    def check(self) -> None:
        _get_json("https://api.vercel.com/v2/user", self.token, self.opener)

    def fetch(self, since: datetime) -> list[Notice]:
        query = {"state": "ERROR", "since": int(since.timestamp() * 1000), "limit": 20}
        if self.team:
            query["teamId"] = self.team
        data = _get_json(f"{self.API}?{urllib.parse.urlencode(query)}", self.token, self.opener)
        notices = []
        for deploy in data.get("deployments", []):
            when = _parse(deploy.get("createdAt"))
            if when is None or when <= since:
                continue
            commit = (deploy.get("meta") or {}).get("githubCommitMessage") or ""
            target = deploy.get("target") or "preview"
            notices.append(Notice(f"vercel:{deploy.get('uid')}", when,
                                  f"{deploy.get('name')} {target} deploy failed" + (f": {_short(commit, 70)}" if commit else "")))
        return notices


class CloudflarePages:
    name = "Cloudflare"
    API = "https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects"

    def __init__(self, token: str, account: str, opener: Callable = urllib.request.urlopen):
        self.token, self.account, self.opener = token, account, opener

    def check(self) -> None:
        self._projects()

    def _projects(self) -> list[str]:
        data = _get_json(self.API.format(account=self.account), self.token, self.opener)
        if not data.get("success", False):
            raise RuntimeError("Cloudflare rejected the request")
        return [p["name"] for p in data.get("result", [])]

    def fetch(self, since: datetime) -> list[Notice]:
        notices = []
        for project in self._projects():
            url = f"{self.API.format(account=self.account)}/{urllib.parse.quote(project)}/deployments?per_page=10"
            for deploy in _get_json(url, self.token, self.opener).get("result", []):
                stage = deploy.get("latest_stage") or {}
                when = _parse(deploy.get("created_on"))
                if stage.get("status") != "failure" or when is None or when <= since:
                    continue
                commit = ((deploy.get("deployment_trigger") or {}).get("metadata") or {}).get("commit_message") or ""
                notices.append(Notice(f"cloudflare:{deploy.get('id')}", when,
                                      f"{project} {deploy.get('environment', 'preview')} deploy failed at {stage.get('name', 'build')}"
                                      + (f": {_short(commit, 70)}" if commit else "")))
        return notices


def format_notices(source: str, notices: list[Notice]) -> str:
    noun = "update" if len(notices) == 1 else "updates"
    lines = [f"{source}: {len(notices)} {noun}"] + [f"- {n.line}" for n in notices[:15]]
    if len(notices) > 15:
        lines.append(f"- and {len(notices) - 15} more")
    return "\n".join(lines)
