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


def stream_chat(config: Config, system: str, user: str) -> Iterator[str]:
    """Yield response text chunks as they arrive."""
    client = _make_client(config)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
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
