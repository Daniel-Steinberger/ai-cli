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
from .context import NoSessionError, get_blocks
from .shell import detect_shell

_OFFSET = re.compile(r"^-(\d+)$")

USAGE = """\
ai — CLI for OpenAI-compatible models

  ai <question...>          Ask anything; e.g. ai how to list files by size
  ai -N <instruction...>    Use the last N commands + output as context
                            e.g. ai -1 explain  (or -3 for the last three)
  ai install [fish]         Install shell integration (enables ai -N)
  ai init [fish]            Print integration snippet (ai init fish | source)
  ai config                 Show effective configuration

Options:
  --model <name>            Override the model for this call
  --debug                   With -N: print the command(s) + output used as context
  -h, --help                Show this help
"""


def _extract_options(args: list[str]) -> tuple[str | None, bool, list[str]]:
    """Pull options (`--model X`/`--model=X`, `--debug`) from anywhere in the args,
    so order does not matter (e.g. `ai -3 --debug explain` works). Returns
    (model_override, debug, remaining_args)."""
    model = None
    debug = False
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--debug":
            debug = True
        elif a.startswith("--model="):
            model = a.split("=", 1)[1]
        elif a == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 1
        else:
            rest.append(a)
        i += 1
    return model, debug, rest


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

    model_override, debug, rest = _extract_options(argv)

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
        blocks = get_blocks(offset)
    except (NoSessionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    if debug:
        _print_debug_blocks(offset, blocks, console)
    shell = detect_shell()
    return ask_mod.explain(config, blocks, instruction, console, shell)


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
