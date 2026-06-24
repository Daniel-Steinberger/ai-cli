"""Config precedence: env > toml > default."""

from ai_cli import config as cfg
from ai_cli.config import DEFAULT_BASE_URL, DEFAULT_MODEL, load_config


def test_defaults(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.setattr(cfg, "_load_toml", lambda: {})
    c = load_config()
    assert c.base_url == DEFAULT_BASE_URL
    assert c.model == DEFAULT_MODEL
    assert c.api_key is None


def test_env_overrides_toml(monkeypatch):
    monkeypatch.setattr(cfg, "_load_toml", lambda: {"model": "from-toml", "base_url": "http://toml"})
    monkeypatch.setenv("AI_MODEL", "from-env")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    c = load_config()
    assert c.model == "from-env"
    assert c.sources["model"].startswith("env:")
    assert c.base_url == "http://toml"
    assert c.sources["base_url"].startswith("config:")


def test_cli_override_wins(monkeypatch):
    monkeypatch.setattr(cfg, "_load_toml", lambda: {})
    monkeypatch.setenv("AI_MODEL", "from-env")
    c = load_config(model_override="from-cli")
    assert c.model == "from-cli"
    assert c.sources["model"] == "cli"
