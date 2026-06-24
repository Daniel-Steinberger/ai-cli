"""Feature 1: ask a free-form question; stream the answer; offer to run a command."""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from .client import ClientError, stream_chat
from .config import Config
from .prompts import ask_system_prompt, explain_system_prompt, explain_user_prompt
from .run import offer_to_run
from .shell import ShellInfo, detect_shell


def _stream_and_render(config: Config, system: str, user: str, console: Console) -> str:
    """Stream the answer, rendering live markdown when on a TTY. Returns full text."""
    parts: list[str] = []
    try:
        if console.is_terminal:
            with Live(console=console, refresh_per_second=12, vertical_overflow="visible") as live:
                for chunk in stream_chat(config, system, user):
                    parts.append(chunk)
                    live.update(Markdown("".join(parts)))
        else:
            for chunk in stream_chat(config, system, user):
                parts.append(chunk)
                console.print(chunk, end="")
            console.print()
    except ClientError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc
    return "".join(parts)


def ask(config: Config, question: str, console: Console) -> int:
    shell = detect_shell()
    answer = _stream_and_render(config, ask_system_prompt(shell), question, console)
    offer_to_run(answer, shell, console)
    return 0


def explain(config: Config, block_cmd: str, block_output: str, exit_code: int | None,
            instruction: str, console: Console, shell: ShellInfo) -> int:
    system = explain_system_prompt(shell)
    user = explain_user_prompt(block_cmd, block_output, exit_code, instruction)
    answer = _stream_and_render(config, system, user, console)
    offer_to_run(answer, shell, console)
    return 0
