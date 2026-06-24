"""Interactive chat mode (`ai -i`). Multi-turn conversation with optional command
context, command execution (with the output fed back into the chat), and readline
line-editing/history. No extra dependencies — readline is stdlib."""

from __future__ import annotations

from rich.console import Console

from .ask import render_stream
from .client import ClientError
from .config import Config, log_dir
from .prompts import chat_context_message, chat_system_prompt, command_result_message
from .run import offer_to_run_capture
from .shell import ShellInfo

EXIT_WORDS = {"exit", "quit", "bye", "q", ":q", "\\q"}

_PROMPT = "[bold green]you[/bold green] › "


def is_exit(text: str) -> bool:
    return text.strip().lower() in EXIT_WORDS


def _history_file():
    return log_dir().parent / "chat_history"


def _setup_readline():
    try:
        import readline
    except ImportError:
        return None
    hist = _history_file()
    try:
        hist.parent.mkdir(parents=True, exist_ok=True)
        if hist.exists():
            readline.read_history_file(str(hist))
    except OSError:
        pass
    return readline


def _save_readline(readline):
    if readline is None:
        return
    try:
        readline.set_history_length(1000)
        readline.write_history_file(str(_history_file()))
    except OSError:
        pass


def chat(config: Config, console: Console, shell: ShellInfo,
         blocks=None, initial_text: str | None = None) -> int:
    if not console.is_terminal:
        console.print("[red]Interactive mode (-i) requires a terminal.[/red]")
        return 1

    readline = _setup_readline()

    system = chat_system_prompt(shell)
    if blocks:
        system += chat_context_message(blocks)
    messages: list[dict] = [{"role": "system", "content": system}]

    console.print(f"[dim]ai chat — model {config.model}. ^D or 'exit' to quit.[/dim]")
    if blocks:
        console.print(f"[dim]Context: the last {len(blocks)} command(s) are available.[/dim]")

    pending = initial_text
    while True:
        if pending is not None:
            line, pending = pending, None
            console.print(f"{_PROMPT}{line}", highlight=False)
        else:
            try:
                line = console.input(_PROMPT)
            except EOFError:
                console.print()
                break
            except KeyboardInterrupt:
                console.print()
                continue

        text = line.strip()
        if not text:
            continue
        if is_exit(text):
            break

        try:
            _run_turn(config, messages, console, shell, text)
        except ClientError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            # drop the dangling user turn so the history stays consistent
            if messages and messages[-1]["role"] == "user":
                messages.pop()

    console.print("[dim]bye[/dim]")
    _save_readline(readline)
    return 0


def _run_turn(config: Config, messages: list[dict], console: Console,
              shell: ShellInfo, user_text: str) -> None:
    """One user turn: stream a reply, then keep running suggested commands and feeding
    their output back as long as the user confirms each one."""
    messages.append({"role": "user", "content": user_text})
    while True:
        answer = render_stream(config, messages, console)
        messages.append({"role": "assistant", "content": answer})

        result = offer_to_run_capture(answer, shell, console)
        if result is None:
            return
        cmd, output, exit_code = result
        messages.append({"role": "user", "content": command_result_message(cmd, output, exit_code)})
        # Loop: stream the assistant's reaction to the actual command output.
