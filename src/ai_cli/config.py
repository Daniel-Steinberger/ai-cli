"""Configuration loading: CLI flags > env vars > TOML file > defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path, user_config_path

APP_NAME = "ai-cli"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def config_dir() -> Path:
    return user_config_path(APP_NAME)


def config_file() -> Path:
    return config_dir() / "config.toml"


def log_dir() -> Path:
    """Directory holding recorded shell-session typescripts (Feature 2)."""
    return user_cache_path(APP_NAME) / "sessions"


@dataclass
class Config:
    api_key: str | None
    base_url: str
    model: str
    # Where each effective value came from, for `ai config`.
    sources: dict[str, str]


def _load_toml() -> dict:
    path = config_file()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_config(model_override: str | None = None) -> Config:
    toml = _load_toml()
    sources: dict[str, str] = {}

    def pick(env_key: str, toml_key: str, default, *, override=None):
        if override is not None:
            sources[toml_key] = "cli"
            return override
        if env_key in os.environ and os.environ[env_key]:
            sources[toml_key] = f"env:{env_key}"
            return os.environ[env_key]
        if toml_key in toml and toml[toml_key]:
            sources[toml_key] = f"config:{config_file()}"
            return toml[toml_key]
        sources[toml_key] = "default"
        return default

    api_key = pick("OPENAI_API_KEY", "api_key", None)
    base_url = pick("OPENAI_BASE_URL", "base_url", DEFAULT_BASE_URL)
    model = pick("AI_MODEL", "model", DEFAULT_MODEL, override=model_override)

    return Config(api_key=api_key, base_url=base_url, model=model, sources=sources)
