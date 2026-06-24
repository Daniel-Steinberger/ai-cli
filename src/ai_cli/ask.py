"""Feature 1: ask a free-form question; stream the answer; offer to run a command."""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from .client import ClientError, stream_messages
from .config import Config
from .prompts import ask_system_prompt, explain_system_prompt, explain_user_prompt
from .run import offer_to_run
from .shell import ShellInfo, detect_shell


def render_stream(config: Config, messages: list[dict], console: Console) -> str:
    """Stream the assistant reply for `messages`, rendering live markdown on a TTY.
    Returns the full reply text. Raises ClientError on an API failure (the caller
    decides whether that is fatal)."""
    parts: list[str] = []
    if console.is_terminal:
        with Live(console=console, refresh_per_second=12, vertical_overflow="visible") as live:
            for chunk in stream_messages(config, messages):
                parts.append(chunk)
                live.update(Markdown("".join(parts)))
    else:
        for chunk in stream_messages(config, messages):
            parts.append(chunk)
            console.print(chunk, end="")
        console.print()
    return "".join(parts)


def _two_message(system: str, user: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def ask(config: Config, question: str, console: Console) -> int:
    shell = detect_shell()
    try:
        answer = render_stream(config, _two_message(ask_system_prompt(shell), question), console)
    except ClientError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    offer_to_run(answer, shell, console)
    return 0


def explain(config: Config, blocks, instruction: str, console: Console,
            shell: ShellInfo) -> int:
    messages = _two_message(explain_system_prompt(shell), explain_user_prompt(blocks, instruction))
    try:
        answer = render_stream(config, messages, console)
    except ClientError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    offer_to_run(answer, shell, console)
    return 0
