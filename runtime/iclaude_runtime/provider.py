"""Optional OpenRouter routing: Claude Code talks to OpenRouter's Anthropic-compatible API.

Claude Code reads ANTHROPIC_AUTH_TOKEN ahead of the subscription login, so setting these
variables in the bridge process moves every bridged session, email triage and briefing
onto OpenRouter without touching the saved claude.ai login.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Mapping, MutableMapping

SETTING = "ICLAUDE_PROVIDER"
KEY = "OPENROUTER_API_KEY"
MODEL = "ICLAUDE_OPENROUTER_MODEL"
FAST_MODEL = "ICLAUDE_OPENROUTER_FAST_MODEL"
DEFAULT_MODEL = "~anthropic/claude-sonnet-latest"
DEFAULT_FAST_MODEL = "~anthropic/claude-haiku-latest"
BASE_URL = "https://openrouter.ai/api"
API = "https://openrouter.ai/api/v1"


def using_openrouter(env: Mapping[str, str]) -> bool:
    return (env.get(SETTING) or "").strip().lower() == "openrouter"


def models(env: Mapping[str, str]) -> tuple[str, str]:
    return (env.get(MODEL) or DEFAULT_MODEL).strip(), (env.get(FAST_MODEL) or DEFAULT_FAST_MODEL).strip()


def claude_env(env: Mapping[str, str]) -> dict[str, str]:
    """The Claude Code variables for OpenRouter; empty when OpenRouter is off.

    The main model stands in for every model alias Claude Code knows (opus, sonnet, fable,
    subagents) and the fast model for haiku, which Claude Code and email triage use for
    quick background calls.
    """
    if not using_openrouter(env) or not env.get(KEY):
        return {}
    main, fast = models(env)
    return {
        "ANTHROPIC_BASE_URL": BASE_URL,
        "ANTHROPIC_AUTH_TOKEN": env[KEY],
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": main,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": main,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": main,
        "ANTHROPIC_DEFAULT_FABLE_MODEL": main,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": fast,
        "CLAUDE_CODE_SUBAGENT_MODEL": main,
    }


def apply(env: Mapping[str, str], process_env: MutableMapping[str, str] = os.environ) -> str:
    """Point Claude Code in this process (and its children) at OpenRouter when configured."""
    values = claude_env(env)
    if not values:
        return "Claude subscription"
    process_env.update(values)
    main, fast = models(env)
    return f"OpenRouter ({main}, fast: {fast})"


def _get(path: str, key: str = "", timeout: float = 15) -> dict:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def check_key(key: str, fetch=_get) -> tuple[bool, str]:
    """Ask OpenRouter about the key; returns (ok, short description or problem)."""
    try:
        data = fetch("/key", key).get("data") or {}
    except urllib.error.HTTPError as exc:
        return False, "OpenRouter rejected the key" if exc.code in (401, 403) else f"OpenRouter returned HTTP {exc.code}"
    except (OSError, ValueError) as exc:
        return False, f"could not reach OpenRouter ({exc})"
    limit = data.get("limit_remaining")
    credit = f", ${limit:.2f} credit left" if isinstance(limit, (int, float)) else ""
    return True, f"key works{credit}"


def check_model(model: str, fetch=_get) -> tuple[bool, str]:
    """Whether OpenRouter lists the model and it supports tool use, which the agent needs."""
    try:
        listed = fetch("/models").get("data") or []
    except (OSError, ValueError):
        return True, "could not list OpenRouter models, not checked"
    wanted = model.split("[")[0]
    found = next((m for m in listed if wanted in (m.get("id"), m.get("canonical_slug"))), None)
    if found is None:
        if wanted.startswith("~"):
            return True, "alias, resolved by OpenRouter"
        return False, "OpenRouter does not list this model"
    if "tools" not in (found.get("supported_parameters") or []):
        return False, "this model does not support tool use, so it cannot run commands, edit files or use connectors"
    return True, found.get("name") or wanted
