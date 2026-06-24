"""`ai install` / `ai init <shell>`: ship the shell integration snippet."""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

from rich.console import Console

from .config import log_dir

SUPPORTED = ("fish",)


def snippet(shell: str = "fish") -> str:
    if shell not in SUPPORTED:
        raise ValueError(f"Unsupported shell '{shell}'. Supported: {', '.join(SUPPORTED)}")
    return files("ai_cli").joinpath(f"data/ai-cli.{shell}").read_text(encoding="utf-8")


def _fish_confd() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "fish" / "conf.d"


def init(shell: str, console: Console) -> int:
    """Print the integration snippet to stdout (for `... | source`)."""
    console.file.write(snippet(shell))
    return 0


def install(shell: str, console: Console) -> int:
    if shell not in SUPPORTED:
        console.print(f"[red]Unsupported shell '{shell}'.[/red] Supported: {', '.join(SUPPORTED)}")
        return 1

    log_dir().mkdir(parents=True, exist_ok=True)
    target_dir = _fish_confd()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ai-cli.{shell}"
    target.write_text(snippet(shell), encoding="utf-8")

    console.print(f"[green]Installed[/green] {shell} integration to {target}")
    console.print("Start a [bold]new[/bold] shell (or `exec fish`) to begin recording.")
    console.print("Then try:  [bold]ls -l[/bold]  followed by  [bold]ai -1 explain[/bold]")
    return 0
