"""Slash commands for the interactive chat (`/clear`, `/help`, …).

The registry below is the single source of truth: the chat loop dispatches through
`dispatch()`, and the input layer builds its completion menu from `completions()`,
so a new command automatically shows up in the autocomplete popup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .config import Config, config_file
from .context import NoSessionError, get_blocks
from .prompts import chat_context_message
from .session import ChatSession

# A slash command is `/name` possibly followed by arguments.
_COMMAND_RE = re.compile(r"^/([A-Za-z][\w-]*)\s*(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Command:
    name: str  # with the leading slash, e.g. "/clear"
    usage: str  # what is shown in the menu, e.g. "/model [name]"
    description: str
    # Returns False to end the chat, True to keep going.
    handler: Callable[[ChatSession, str], bool]


def render_config(console: Console, config: Config) -> None:
    """The `ai config` table — shared by the CLI subcommand and `/config`."""
    table = Table(title="ai configuration")
    table.add_column("setting", style="bold")
    table.add_column("value")
    table.add_column("source")

    key_display = "<set>" if config.api_key else "[red]<missing>[/red]"
    table.add_row("api_key", key_display, config.sources.get("api_key", "default"))
    table.add_row("base_url", config.base_url, config.sources.get("base_url", "default"))
    table.add_row("model", config.model, config.sources.get("model", "default"))
    console.print(table)
    console.print(f"\nConfig file: {config_file()}")


def _cmd_help(session: ChatSession, args: str) -> bool:
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="dim")
    for cmd in COMMANDS:
        # escape: usage strings like "/model [name]" would be read as Rich markup.
        table.add_row(escape(cmd.usage), cmd.description)
    session.console.print(table)
    session.console.print(
        "[dim]Tab completes commands. ^D or 'exit' quits. Anything else goes to the model.[/dim]",
        highlight=False,
    )
    return True


def _cmd_clear(session: ChatSession, args: str) -> bool:
    session.reset()
    session.console.clear()
    note = f" Context ({' and '.join(session.notes)}) kept." if session.notes else ""
    session.console.print(f"[dim]History cleared.{note}[/dim]", highlight=False)
    return True


def _cmd_exit(session: ChatSession, args: str) -> bool:
    return False


def _cmd_model(session: ChatSession, args: str) -> bool:
    name = args.strip()
    if not name:
        source = session.config.sources.get("model", "default")
        session.console.print(
            f"[dim]model:[/dim] {session.config.model} [dim]({source})[/dim]", highlight=False
        )
        return True
    previous = session.config.model
    session.config.model = name
    session.config.sources["model"] = "chat"
    session.console.print(f"[dim]model:[/dim] {previous} [dim]→[/dim] {name}", highlight=False)
    return True


def _cmd_config(session: ChatSession, args: str) -> bool:
    render_config(session.console, session.config)
    return True


def _cmd_context(session: ChatSession, args: str) -> bool:
    raw = args.strip().lstrip("-") or "1"
    if not raw.isdigit() or int(raw) < 1:
        session.console.print(
            "[yellow]Usage:[/yellow] " + escape("/context [-N]  (N = number of commands)"),
            highlight=False,
        )
        return True
    n = int(raw)
    try:
        blocks = get_blocks(n)
    except (NoSessionError, ValueError) as exc:
        session.console.print(f"[yellow]No command context:[/yellow] {exc}", highlight=False)
        return True
    session.add_context(chat_context_message(blocks), f"the last {len(blocks)} command(s)")
    session.console.print(
        f"[dim]Loaded the last {len(blocks)} command(s) as context.[/dim]", highlight=False
    )
    return True


COMMANDS: list[Command] = [
    Command("/clear", "/clear", "Clear the conversation history and the screen", _cmd_clear),
    Command("/context", "/context [-N]", "Load the last N commands + output as context",
            _cmd_context),
    Command("/model", "/model [name]", "Show or switch the model for this session", _cmd_model),
    Command("/config", "/config", "Show the effective configuration", _cmd_config),
    Command("/help", "/help", "List the available commands", _cmd_help),
    Command("/exit", "/exit", "End the chat", _cmd_exit),
]


def find(name: str) -> Command | None:
    """Look up a command by name (with or without the leading slash)."""
    wanted = name if name.startswith("/") else f"/{name}"
    for cmd in COMMANDS:
        if cmd.name == wanted:
            return cmd
    return None


def split(text: str) -> tuple[Command, str] | None:
    """Return (command, args) if `text` starts with a known slash command, else None.

    Unknown `/…` input is deliberately *not* an error: `/tmp/foo — what is this?`
    should reach the model like any other question.
    """
    m = _COMMAND_RE.match(text.strip())
    if not m:
        return None
    cmd = find(m.group(1))
    return (cmd, m.group(2).strip()) if cmd else None


def dispatch(session: ChatSession, text: str) -> bool:
    """Run the slash command in `text`. Only call when `split()` matched."""
    matched = split(text)
    if matched is None:
        return True
    cmd, args = matched
    return cmd.handler(session, args)


def completions(prefix: str) -> list[Command]:
    """Commands whose name starts with `prefix` (e.g. "/cl" -> /clear)."""
    return [c for c in COMMANDS if c.name.startswith(prefix)]
