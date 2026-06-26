"""Entry point and argument dispatch for the `ai` command.

Usage:
  ai <question...>            Ask anything (Feature 1). Suggested commands can be run.
  ai -N <instruction...>      Explain the N-th last command + its output (Feature 2).
  ai install [fish]           Install shell integration for Feature 2.
  ai init [fish]              Print the integration snippet (for `... | source`).
  ai config                   Show the effective configuration.

Global option (may lead the args):  --model <name>
"""

from __future__ import annotations

import re
import sys

from rich.console import Console

from . import ask as ask_mod
from . import chat as chat_mod
from . import integration
from .config import config_file, load_config
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

  ai <question...>          Ask anything; e.g. ai how to list files by size
  <cmd> | ai <question...>  Pipe input as context; e.g. cat err.log | ai "why?"
  ai -N <instruction...>    Use the last N commands + output as context
                            e.g. ai -1 explain  (or -3 for the last three)
  ai -i [-N] [text...]      Interactive chat; optional -N / text seed the context
  ai install [fish]         Install shell integration (enables ai -N)
  ai init [fish]            Print integration snippet (ai init fish | source)
  ai config                 Show effective configuration

Options:
  -i, --interactive         Start an interactive chat (^D or 'exit' to quit)
  --model <name>            Override the model for this call
  --debug                   With -N: print the command(s) + output used as context
  -h, --help                Show this help
"""


def _extract_options(args: list[str]) -> tuple[str | None, bool, bool, list[str]]:
    """Pull options (`--model X`/`--model=X`, `--debug`, `-i`/`--interactive`) from
    anywhere in the args, so order does not matter (e.g. `ai -3 --debug explain` or
    `ai -i -1`). Returns (model_override, debug, interactive, remaining_args)."""
    model = None
    debug = False
    interactive = False
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--debug":
            debug = True
        elif a in ("-i", "--interactive"):
            interactive = True
        elif a.startswith("--model="):
            model = a.split("=", 1)[1]
        elif a == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 1
        else:
            rest.append(a)
        i += 1
    return model, debug, interactive, rest


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    console = Console()

    if not argv or argv[0] in ("-h", "--help", "help"):
        console.print(USAGE, highlight=False)
        return 0

    # Subcommands.
    if argv[0] == "install":
        return integration.install(argv[1] if len(argv) > 1 else "fish", console)
    if argv[0] == "init":
        return integration.init(argv[1] if len(argv) > 1 else "fish", console)
    if argv[0] == "config":
        return _show_config(console)

    model_override, debug, interactive, rest = _extract_options(argv)

    # Read piped stdin first (e.g. `… | ai "translate"`); this also lets us treat a
    # bare `… | ai` (no args) as a real request rather than printing usage.
    stdin_text = _read_piped_stdin()

    if not rest and not interactive and not stdin_text:
        console.print(USAGE, highlight=False)
        return 0

    config = load_config(model_override=model_override)

    # A leading -N offset selects command context (used by both -i and Feature 2).
    offset = None
    if rest:
        m = _OFFSET.match(rest[0])
        if m:
            offset = int(m.group(1))
            rest = rest[1:]

    if interactive:
        return _interactive(config, offset, " ".join(rest).strip(), console, stdin_text)

    if offset is not None:
        instruction = " ".join(rest).strip() or "explain"
        return _explain(config, offset, instruction, console, debug=debug, stdin_text=stdin_text)

    # Feature 1: free-form question (possibly with piped stdin as input).
    return ask_mod.ask(config, " ".join(rest).strip(), console, stdin_text=stdin_text)


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
    from rich.table import Table

    config = load_config()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
