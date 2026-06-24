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
from . import integration
from .config import config_file, load_config
from .context import NoSessionError, get_block
from .shell import detect_shell

_OFFSET = re.compile(r"^-(\d+)$")

USAGE = """\
ai — CLI for OpenAI-compatible models

  ai <question...>          Ask anything; e.g. ai how to list files by size
  ai -N <instruction...>    Use the N-th last command + output as context
                            e.g. ai -1 explain
  ai install [fish]         Install shell integration (enables ai -N)
  ai init [fish]            Print integration snippet (ai init fish | source)
  ai config                 Show effective configuration

Options:
  --model <name>            Override the model for this call
  --debug                   With -N: print the command(s) + output used as context
  -h, --help                Show this help
"""


def _consume_leading_options(args: list[str]) -> tuple[str | None, bool, list[str]]:
    """Pull leading options (`--model X`, `--debug`) off the front of the args.
    Returns (model_override, debug, remaining_args)."""
    model = None
    debug = False
    while args and args[0].startswith("--"):
        if args[0] == "--debug":
            debug = True
            args = args[1:]
        elif args[0].startswith("--model="):
            model = args[0].split("=", 1)[1]
            args = args[1:]
        elif args[0] == "--model" and len(args) >= 2:
            model = args[1]
            args = args[2:]
        else:
            break
    return model, debug, args


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

    model_override, debug, rest = _consume_leading_options(argv)

    if not rest:
        console.print(USAGE, highlight=False)
        return 0

    config = load_config(model_override=model_override)

    # Feature 2: leading -N offset.
    m = _OFFSET.match(rest[0])
    if m:
        offset = int(m.group(1))
        instruction = " ".join(rest[1:]).strip() or "explain"
        return _explain(config, offset, instruction, console, debug=debug)

    # Feature 1: free-form question.
    question = " ".join(rest).strip()
    return ask_mod.ask(config, question, console)


def _explain(config, offset: int, instruction: str, console: Console, *, debug: bool = False) -> int:
    try:
        block = get_block(offset)
    except (NoSessionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    if debug:
        _print_debug_block(offset, block, console)
    shell = detect_shell()
    return ask_mod.explain(
        config, block.cmd, block.output, block.exit_code, instruction, console, shell
    )


def _print_debug_block(offset: int, block, console: Console) -> None:
    from rich.panel import Panel

    exit_str = "?" if block.exit_code is None else str(block.exit_code)
    body = (
        f"[bold]command:[/bold] {block.cmd}\n"
        f"[bold]exit:[/bold] {exit_str}\n"
        f"[bold]output:[/bold]\n{block.output or '[dim](no output)[/dim]'}"
    )
    console.print(
        Panel(body, title=f"[dim]--debug: context used (-{offset})[/dim]",
              border_style="yellow", highlight=False)
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
