"""Extract a suggested command from a model answer and (optionally) run it."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from rich.console import Console
from rich.prompt import Confirm
from rich.syntax import Syntax

from .context import strip_ansi
from .shell import ShellInfo

# First fenced code block; capture its optional language tag and body.
_FENCE = re.compile(r"```([\w.-]*)\r?\n(.*?)```", re.DOTALL)

_SHELL_LANGS = {"bash", "sh", "zsh", "fish", "shell", "console", "ps1", "powershell", ""}

_MAX_CAPTURE_CHARS = 6000


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


def _confirm_and_get_argv(answer: str, shell: ShellInfo, console: Console) -> tuple[str, list[str]] | None:
    """Show a suggested command and ask whether to run it.
    Returns (command, argv) if confirmed, else None."""
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
    return command, _shell_exec_argv(shell, command)


def offer_to_run(answer: str, shell: ShellInfo, console: Console) -> int | None:
    """If the answer contains a command, show it and offer to execute it (Feature 1).
    Inherits the terminal (so sudo can prompt for a password). Returns the exit code,
    or None if nothing was run."""
    result = _confirm_and_get_argv(answer, shell, console)
    if result is None:
        return None
    _command, argv = result
    try:
        proc = subprocess.run(argv)
        return proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]Failed to run command:[/red] {exc}")
        return None


def offer_to_run_capture(answer: str, shell: ShellInfo, console: Console) -> tuple[str, str, int] | None:
    """Chat variant: show + confirm, then run the command through a PTY so its output
    is shown live AND captured. Returns (command, clean_output, exit_code), or None if
    nothing was run.

    A PTY is used (not piped subprocess) so that interactive programs and `sudo` work:
    sudo reads its password from the tty with echo disabled, so it is neither shown nor
    captured. Falls back to a piped subprocess where `pty` is unavailable (e.g. Windows).
    """
    result = _confirm_and_get_argv(answer, shell, console)
    if result is None:
        return None
    command, argv = result

    try:
        import pty
    except ImportError:
        return _run_capture_subprocess(command, argv, console)

    chunks: list[bytes] = []

    def _read(fd: int) -> bytes:
        data = os.read(fd, 1024)
        chunks.append(data)
        return data

    try:
        status = pty.spawn(argv, _read)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Failed to run command:[/red] {exc}")
        return None
    exit_code = os.waitstatus_to_exitcode(status)
    raw = b"".join(chunks).decode("utf-8", errors="replace")
    return command, _clean_capture(raw), exit_code


def _run_capture_subprocess(command: str, argv: list[str], console: Console) -> tuple[str, str, int] | None:
    """Fallback capture without a PTY (no live colour/tty fidelity)."""
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]Failed to run command:[/red] {exc}")
        return None
    console.print(proc.stdout, end="")
    return command, _clean_capture(proc.stdout), proc.returncode


def _clean_capture(raw: str) -> str:
    text = strip_ansi(raw).strip("\n")
    if len(text) > _MAX_CAPTURE_CHARS:
        half = _MAX_CAPTURE_CHARS // 2
        omitted = len(text) - 2 * half
        text = f"{text[:half]}\n... [{omitted} characters omitted] ...\n{text[-half:]}"
    return text
