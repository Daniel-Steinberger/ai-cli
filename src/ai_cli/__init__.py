"""ai-cli: a CLI for OpenAI-API-compatible models with shell-context awareness."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    # pyproject.toml is the single source of truth for the version.
    __version__ = _version("ai-cli")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
