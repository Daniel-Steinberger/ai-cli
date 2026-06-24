"""Thin wrapper around the OpenAI-compatible client with streaming."""

from __future__ import annotations

from collections.abc import Iterator

from .config import Config


class ClientError(RuntimeError):
    pass


def _make_client(config: Config):
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ClientError("The 'openai' package is not installed.") from exc

    if not config.api_key:
        raise ClientError(
            "No API key configured. Set OPENAI_API_KEY or add api_key to "
            "the config file (see `ai config`)."
        )
    return OpenAI(api_key=config.api_key, base_url=config.base_url)


def stream_messages(config: Config, messages: list[dict]) -> Iterator[str]:
    """Yield response text chunks for a full message list as they arrive."""
    client = _make_client(config)
    try:
        stream = client.chat.completions.create(
            model=config.model,
            messages=messages,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
    except Exception as exc:  # noqa: BLE001 - surface any SDK/HTTP error cleanly
        raise ClientError(f"API request failed: {exc}") from exc


def stream_chat(config: Config, system: str, user: str) -> Iterator[str]:
    """Yield response text chunks for a single system+user exchange."""
    return stream_messages(
        config,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
