import io
import urllib.error

import pytest

from iclaude_runtime import checks, cli, provider

ON = {provider.SETTING: "openrouter", provider.KEY: "sk-or-test"}


def test_off_by_default():
    assert not provider.using_openrouter({})
    assert provider.claude_env({}) == {}
    assert provider.claude_env({provider.SETTING: "openrouter"}) == {}
    target = {}
    assert provider.apply({}, target) == "Claude subscription" and target == {}


def test_claude_env_maps_main_and_fast_models():
    env = {**ON, provider.MODEL: "openai/gpt-5", provider.FAST_MODEL: "openai/gpt-5-mini"}
    values = provider.claude_env(env)
    assert values["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
    assert values["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test" and values["ANTHROPIC_API_KEY"] == ""
    for name in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                 "ANTHROPIC_DEFAULT_FABLE_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
        assert values[name] == "openai/gpt-5"
    assert values["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "openai/gpt-5-mini"
    target = {}
    assert provider.apply(env, target).startswith("OpenRouter (openai/gpt-5")
    assert target == values


def test_defaults_are_claude_through_openrouter():
    assert provider.models(ON) == (provider.DEFAULT_MODEL, provider.DEFAULT_FAST_MODEL)


def _http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def test_check_key():
    assert provider.check_key("k", lambda path, key: {"data": {"limit_remaining": 12.5}}) == (True, "key works, $12.50 credit left")
    assert provider.check_key("k", lambda path, key: {"data": {"limit_remaining": None}}) == (True, "key works")

    def reject(path, key):
        raise _http_error(401)

    assert provider.check_key("k", reject) == (False, "OpenRouter rejected the key")


MODELS = {"data": [
    {"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "supported_parameters": ["tools", "max_tokens"]},
    {"id": "some/chat-only", "name": "Chat only", "supported_parameters": ["max_tokens"]},
]}


def test_check_model():
    fetch = lambda path, key="": MODELS
    assert provider.check_model("anthropic/claude-sonnet-4.6", fetch) == (True, "Claude Sonnet 4.6")
    assert provider.check_model("anthropic/claude-sonnet-4.6[1m]", fetch)[0]
    assert not provider.check_model("some/chat-only", fetch)[0]
    assert provider.check_model("nope/missing", fetch) == (False, "OpenRouter does not list this model")
    assert provider.check_model("~anthropic/claude-sonnet-latest", fetch)[0]


def test_preflight_uses_openrouter_key_instead_of_login():
    result = checks.check_model_provider(ON)
    assert result.ok and "OpenRouter" in result.detail
    assert not checks.check_model_provider({provider.SETTING: "openrouter"}).ok


@pytest.fixture
def saved(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setenv("INKBOX_CLAUDE_ENV_FILE", str(tmp_path / ".env"))
    for name in (provider.SETTING, provider.KEY, provider.MODEL, provider.FAST_MODEL, "CLAUDE_MODEL"):
        monkeypatch.delenv(name, raising=False)

    def save(name, value):
        store[name] = value
        monkeypatch.setenv(name, value)

    monkeypatch.setattr(cli, "_save", save)
    return store


def test_model_openrouter_validates_then_saves(saved, monkeypatch, capsys):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "sk-or-new")
    monkeypatch.setattr(provider, "check_key", lambda key: (key == "sk-or-new", "key works"))
    monkeypatch.setattr(provider, "check_model", lambda name: (name != "bad/model", "ok"))
    assert cli.cmd_model("openrouter", "bad/model", None, False, False) == 1
    assert saved == {}
    assert cli.cmd_model("openrouter", "openai/gpt-5", None, False, False) == 0
    assert saved == {provider.KEY: "sk-or-new", provider.MODEL: "openai/gpt-5",
                     provider.FAST_MODEL: provider.DEFAULT_FAST_MODEL, provider.SETTING: "openrouter"}
    out = capsys.readouterr().out
    assert "connectors" in out and "Switch back" in out
    assert cli.cmd_model("claude", None, None, False, False) == 0
    assert saved[provider.SETTING] == "claude" and "stays saved" in capsys.readouterr().out


def test_model_openrouter_rejects_bad_key(saved, monkeypatch):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "sk-or-bad")
    monkeypatch.setattr(provider, "check_key", lambda key: (False, "OpenRouter rejected the key"))
    assert cli.cmd_model("openrouter", None, None, False, False) == 1
    assert saved == {}
