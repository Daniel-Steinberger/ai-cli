"""Entry point and argument dispatch for the `ai` command.

Interactive chat is the default; `-p/--print` prints a single answer and exits.

Usage:
  ai                          Start the interactive chat.
  ai <question...>            Chat, seeded with the question.
  ai -N [instruction...]      Chat with the last N commands + output as context.
  ai -p <question...>         Print one answer (Feature 1). Suggested commands can be run.
  ai -p -N [instruction...]   Print one explanation of the last N commands (Feature 2).
  ai install [fish]           Install shell integration for Feature 2.
  ai init [fish]              Print the integration snippet (for `... | source`).
  ai config                   Show the effective configuration.

Global option (may lead the args):  --model <name>
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

from rich.console import Console

from . import ask as ask_mod
from . import chat as chat_mod
from . import commands
from . import integration
from .config import load_config
from .context import NoSessionError, get_blocks
from .shell import detect_shell

_OFFSET = re.compile(r"^-(\d+)$")


def _read_piped_stdin() -> str | None:
    """Return stdin content if something was piped in (stdin is not a TTY), else None."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return None
    data = data.strip()
    return data or None

USAGE = """\
ai — CLI for OpenAI-compatible models

  ai                        Interactive chat (the default; /help for commands)
  ai <question...>          Chat, seeded with the question
                            e.g. ai how to list files by size
  ai -N [text...]           Chat with the last N commands + output as context
                            e.g. ai -1 explain  (or -3 for the last three)
  <cmd> | ai [question...]  Pipe input as context; e.g. cat err.log | ai "why?"
  ai -p <question...>       Ask anything, print the answer and exit
  ai -p -N [text...]        Print an explanation of the last N commands
  ai install [fish]         Install shell integration (enables ai -N)
  ai init [fish]            Print integration snippet (ai init fish | source)
  ai config                 Show effective configuration

Options:
  -p, --print               Print a single answer instead of starting a chat
  -i, --interactive         Start an interactive chat (now the default; kept for
                            compatibility)
  --model <name>            Override the model for this call
  --debug                   With -N: print the command(s) + output used as context
  -h, --help                Show this help
"""


@dataclass
class Options:
    model: str | None = None
    debug: bool = False
    print_mode: bool = False
    rest: list[str] = field(default_factory=list)


def _extract_options(args: list[str]) -> Options:
    """Pull options (`--model X`/`--model=X`, `--debug`, `-p`/`--print`) from anywhere
    in the args, so order does not matter (e.g. `ai -3 --debug explain` or
    `ai -p -1`). `-i`/`--interactive` is accepted but a no-op: chat is the default."""
    opts = Options()
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--debug":
            opts.debug = True
        elif a in ("-p", "--print"):
            opts.print_mode = True
        elif a in ("-i", "--interactive"):
            pass  # default behaviour; kept so old invocations keep working
        elif a.startswith("--model="):
            opts.model = a.split("=", 1)[1]
        elif a == "--model" and i + 1 < len(args):
            opts.model = args[i + 1]
            i += 1
        else:
            opts.rest.append(a)
        i += 1
    return opts


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    console = Console()

    if argv and argv[0] in ("-h", "--help", "help"):
        console.print(USAGE, highlight=False)
        return 0

    # Subcommands.
    if argv:
        if argv[0] == "install":
            return integration.install(argv[1] if len(argv) > 1 else "fish", console)
        if argv[0] == "init":
            return integration.init(argv[1] if len(argv) > 1 else "fish", console)
        if argv[0] == "config":
            return _show_config(console)

    opts = _extract_options(argv)
    rest = opts.rest

    # Read piped stdin first (e.g. `… | ai "translate"`); this also lets us treat a
    # bare `… | ai` (no args) as a real request.
    stdin_text = _read_piped_stdin()

    config = load_config(model_override=opts.model)

    # A leading -N offset selects command context (used by chat and Feature 2 alike).
    offset = None
    if rest:
        m = _OFFSET.match(rest[0])
        if m:
            offset = int(m.group(1))
            rest = rest[1:]

    text = " ".join(rest).strip()

    # Chat is the default; without a usable terminal we fall back to printing so that
    # `ai frage > out.txt` and non-interactive scripts keep working.
    if not opts.print_mode and console.is_terminal:
        return _interactive(config, offset, text, console, stdin_text)

    if offset is not None:
        return _explain(config, offset, text or "explain", console,
                        debug=opts.debug, stdin_text=stdin_text)

    if not text and not stdin_text:
        console.print(USAGE, highlight=False)
        return 0

    # Feature 1: free-form question (possibly with piped stdin as input).
    return ask_mod.ask(config, text, console, stdin_text=stdin_text)


def _interactive(config, offset: int | None, initial_text: str, console: Console,
                 stdin_text: str | None) -> int:
    shell = detect_shell()
    blocks = None
    if offset is not None:
        try:
            blocks = get_blocks(offset)
        except (NoSessionError, ValueError) as exc:
            console.print(f"[yellow]No command context:[/yellow] {exc}")
    return chat_mod.chat(config, console, shell, blocks=blocks,
                         initial_text=initial_text or None, piped_context=stdin_text)


def _explain(config, offset: int, instruction: str, console: Console, *,
             debug: bool = False, stdin_text: str | None = None) -> int:
    try:
        blocks = get_blocks(offset)
    except (NoSessionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    if debug:
        _print_debug_blocks(offset, blocks, console)
    shell = detect_shell()
    return ask_mod.explain(config, blocks, instruction, console, shell, stdin_text=stdin_text)


def _print_debug_blocks(offset: int, blocks, console: Console) -> None:
    from rich.panel import Panel

    sections = []
    for i, b in enumerate(blocks, 1):
        exit_str = "?" if b.exit_code is None else str(b.exit_code)
        sections.append(
            f"[bold cyan]\\[{i}/{len(blocks)}] command:[/bold cyan] {b.cmd}\n"
            f"[bold]exit:[/bold] {exit_str}\n"
            f"[bold]output:[/bold]\n{b.output or '[dim](no output)[/dim]'}"
        )
    title = f"[dim]--debug: {len(blocks)} command(s) used as context (-{offset})[/dim]"
    console.print(
        Panel("\n\n".join(sections), title=title, border_style="yellow", highlight=False)
    )


def _show_config(console: Console) -> int:
    commands.render_config(console, load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
