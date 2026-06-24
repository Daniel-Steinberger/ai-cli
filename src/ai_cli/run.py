"""Extract a suggested command from a model answer and (optionally) run it."""

from __future__ import annotations

import re
import shutil
import subprocess

from rich.console import Console
from rich.prompt import Confirm
from rich.syntax import Syntax

from .shell import ShellInfo

# First fenced code block; capture its optional language tag and body.
_FENCE = re.compile(r"```([\w.-]*)\r?\n(.*?)```", re.DOTALL)

_SHELL_LANGS = {"bash", "sh", "zsh", "fish", "shell", "console", "ps1", "powershell", ""}


def extract_command(answer: str) -> str | None:
    """Return the first fenced code block that looks like a runnable command."""
    for m in _FENCE.finditer(answer):
        lang = m.group(1).lower()
        if lang not in _SHELL_LANGS:
            continue
        body = m.group(2).strip()
        if not body:
            continue
        # Drop leading "$ " prompts that models sometimes add.
        lines = [re.sub(r"^\s*\$\s+", "", ln) for ln in body.splitlines()]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            return cleaned
    return None


def _shell_exec_argv(shell: ShellInfo, command: str) -> list[str]:
    name = shell.name if shutil.which(shell.name) else "sh"
    if name in ("fish", "zsh", "bash", "sh", "dash", "ksh", "tcsh", "csh"):
        return [name, "-c", command]
    # PowerShell / unknown: fall back to a POSIX shell if present.
    if shutil.which("bash"):
        return ["bash", "-c", command]
    return ["sh", "-c", command]


def offer_to_run(answer: str, shell: ShellInfo, console: Console) -> int | None:
    """If the answer contains a command, show it and offer to execute it.
    Returns the command's exit code, or None if nothing was run."""
    command = extract_command(answer)
    if not command:
        return None

    console.print()
    console.print("[bold]Suggested command:[/bold]")
    console.print(Syntax(command, shell.name if shell.name != "unknown" else "bash"))
    if not console.is_terminal:
        return None  # never auto-run when not interactive
    try:
        if not Confirm.ask("Run it?", default=False, console=console):
            return None
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None

    argv = _shell_exec_argv(shell, command)
    try:
        proc = subprocess.run(argv)
        return proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]Failed to run command:[/red] {exc}")
        return None
