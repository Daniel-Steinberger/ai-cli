"""Interactive chat mode — the default when `ai` is invoked without `-p`.

Multi-turn conversation with optional command context, slash commands (see
`commands.py`) with an autocompletion popup, and command execution whose output is
fed back into the conversation.

Line editing comes from `prompt_toolkit` (needed for the completion menu); if it is
unavailable we fall back to stdlib `readline`, which gives history and editing but
no popup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rich.console import Console

from . import commands, references
from .ask import render_stream
from .client import ClientError
from .config import Config, log_dir
from .prompts import (
    chat_context_message,
    chat_system_prompt,
    command_result_message,
    stdin_context_message,
)
from .run import offer_to_run_capture
from .session import ChatSession
from .shell import ShellInfo

EXIT_WORDS = {"exit", "quit", "bye", "q", ":q", "\\q"}

_PROMPT = "[bold green]you[/bold green] › "

# ANSI variant for the builtin input() when readline is active. Rich's
# console.input() prints the prompt and then calls input("") with an empty
# string, so readline stays blind to the prompt's on-screen width and its
# cursor math (backspace, line wrapping) is off by the prompt width. Passing
# the prompt to input() directly fixes that, but the non-printing escape
# sequences must be wrapped in \001..\002 (RL_PROMPT_{START,END}_IGNORE) so
# readline excludes them from the width. Visible width stays "you › " (6).
_PROMPT_READLINE = "\001\033[1;32m\002you\001\033[0m\002 › "


def is_exit(text: str) -> bool:
    return text.strip().lower() in EXIT_WORDS


def _history_file(name: str = "chat_history"):
    return log_dir().parent / name


# --------------------------------------------------------------------------- input


class _ReadlineReader:
    """Fallback line reader: stdlib readline (no completion popup)."""

    def __init__(self, console: Console):
        self.console = console
        self.readline = self._setup()

    def _setup(self):
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

    def read(self) -> str:
        if self.readline is not None:
            return input(_PROMPT_READLINE)
        return self.console.input(_PROMPT)

    def close(self) -> None:
        if self.readline is None:
            return
        try:
            self.readline.set_history_length(1000)
            self.readline.write_history_file(str(_history_file()))
        except OSError:
            pass


def _current_token(text: str) -> str:
    """The token the cursor sits in ("" right after whitespace)."""
    if not text or text[-1].isspace():
        return ""
    return text.rsplit(maxsplit=1)[-1]


def _chat_completer():
    """Completer for the chat prompt: slash commands and `@path` references.

    Built lazily because the base classes come from prompt_toolkit.
    """
    from prompt_toolkit.completion import Completer, Completion, PathCompleter
    from prompt_toolkit.document import Document

    paths = PathCompleter(expanduser=True)

    class _ChatCompleter(Completer):
        def get_completions(self, document, complete_event):
            before = document.text_before_cursor
            token = _current_token(before)

            # Slash commands: only as the very first token of the line.
            if token.startswith("/") and token == before:
                for cmd in commands.completions(token):
                    yield Completion(
                        cmd.name,
                        start_position=-len(token),
                        display=cmd.usage,
                        display_meta=cmd.description,
                    )
                return

            # `@path` references: anywhere in the line. Delegate to PathCompleter on
            # the part after the `@`; start_position is relative to the cursor, which
            # sits at the end of both documents, so it carries over unchanged.
            if token.startswith("@"):
                fragment = token[1:]
                sub = Document(fragment, len(fragment))
                for completion in paths.get_completions(sub, complete_event):
                    candidate = fragment[:len(fragment) + completion.start_position] \
                        + completion.text
                    is_dir = Path(candidate).expanduser().is_dir()
                    yield Completion(
                        # Append the separator for directories so the next path
                        # segment can be completed right away.
                        completion.text + ("/" if is_dir else ""),
                        start_position=completion.start_position,
                        display=completion.display,
                        display_meta="directory" if is_dir else "file",
                    )

    return _ChatCompleter()


class _PromptToolkitReader:
    """Line reader with a live completion popup for slash commands."""

    def __init__(self, *, input=None, output=None):
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.shortcuts import CompleteStyle
        from prompt_toolkit.styles import Style

        # prompt_toolkit's FileHistory format differs from readline's, hence its own file.
        hist_path = _history_file("chat_history.ptk")
        try:
            hist_path.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(hist_path))
        except OSError:
            history = None

        self._prompt = FormattedText([("class:you", "you"), ("", " › ")])
        self._session = PromptSession(
            history=history,
            completer=_chat_completer(),
            complete_while_typing=True,
            complete_style=CompleteStyle.COLUMN,
            style=Style.from_dict({
                "you": "bold ansigreen",
                "completion-menu.completion": "bg:ansiblack ansiwhite",
                "completion-menu.completion.current": "bg:ansiblue ansiwhite bold",
                "completion-menu.meta.completion": "bg:ansiblack ansibrightblack",
                "completion-menu.meta.completion.current": "bg:ansiblue ansiwhite",
            }),
            **({"input": input} if input is not None else {}),
            **({"output": output} if output is not None else {}),
        )

    def read(self) -> str:
        return self._session.prompt(self._prompt)

    def close(self) -> None:
        pass  # FileHistory persists on every accepted line


def _build_input(console: Console):
    """Return a line reader with .read() / .close(), preferring prompt_toolkit."""
    try:
        return _PromptToolkitReader()
    except Exception:
        # ImportError, or a terminal prompt_toolkit cannot drive.
        return _ReadlineReader(console)


def _reopen_tty() -> bool:
    """When stdin was piped (e.g. `cat x | ai`), reconnect fd 0 to the controlling
    terminal so we can still read interactive input. Returns True on success."""
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        return False
    try:
        os.dup2(fd, 0)
    finally:
        os.close(fd)
    try:
        sys.stdin = os.fdopen(0, "r", closefd=False)
    except OSError:
        pass
    return True


# ---------------------------------------------------------------------------- loop


def chat(config: Config, console: Console, shell: ShellInfo,
         blocks=None, initial_text: str | None = None, piped_context: str | None = None) -> int:
    if not console.is_terminal:
        console.print("[red]Interactive mode requires a terminal (use -p to print).[/red]")
        return 1

    # If input was piped in, reconnect to the terminal so the chat can still read input.
    input_ok = sys.stdin.isatty() or _reopen_tty()
    if not input_ok and not initial_text:
        console.print("[red]Interactive mode needs a terminal for input.[/red]")
        return 1

    session = ChatSession(config=config, console=console, shell=shell,
                          system=chat_system_prompt(shell))
    if blocks:
        session.add_context(chat_context_message(blocks), f"the last {len(blocks)} command(s)")
    if piped_context:
        session.add_context(stdin_context_message(piped_context), "piped input")

    console.print(
        f"[dim]ai chat — model {config.model}. /help for commands, ^D or 'exit' to quit.[/dim]"
    )
    if session.notes:
        console.print(f"[dim]Context: {' and '.join(session.notes)} available.[/dim]")

    reader = _build_input(console) if input_ok else None

    pending = initial_text
    while True:
        if pending is not None:
            line, pending = pending, None
            console.print(f"{_PROMPT}{line}", highlight=False)
        elif reader is None:
            break  # seeded turn done; no terminal to keep reading from
        else:
            try:
                line = reader.read()
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
        if commands.split(text) is not None:
            if not commands.dispatch(session, text):
                break
            continue

        try:
            _run_turn(session, text)
        except ClientError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            # drop the dangling user turn so the history stays consistent
            if session.messages and session.messages[-1]["role"] == "user":
                session.messages.pop()

    console.print("[dim]bye[/dim]")
    if reader is not None:
        reader.close()
    return 0


def _run_turn(session: ChatSession, user_text: str) -> None:
    """One user turn: stream a reply, then keep running suggested commands and feeding
    their output back as long as the user confirms each one."""
    console, messages = session.console, session.messages
    messages.append({"role": "user", "content": references.expand(user_text, console)})
    while True:
        answer = render_stream(session.config, messages, console)
        messages.append({"role": "assistant", "content": answer})

        result = offer_to_run_capture(answer, session.shell, console)
        if result is None:
            return
        cmd, output, exit_code = result
        messages.append({"role": "user", "content": command_result_message(cmd, output, exit_code)})
        # Loop: stream the assistant's reaction to the actual command output.
