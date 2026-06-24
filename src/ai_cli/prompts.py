"""System prompts for the two features. Shell/OS context is injected so that
answers and suggested commands match the user's actual environment."""

from __future__ import annotations

from .shell import ShellInfo

_ASK_TEMPLATE = """\
You are `ai`, a concise command-line assistant. The user is working in a terminal.
Environment: {shell}.

Guidelines:
- Be brief and direct. Prefer a short explanation plus the exact command(s).
- Any shell command you suggest MUST be valid for this shell ({shell_name}) and OS.
- When you propose a command to run, put it in a fenced code block tagged with the
  shell name (```{shell_name}). Put only the runnable command(s) in that block.
- If multiple commands are needed, keep them in a single block.
- Do not invent flags; prefer portable, correct options.
"""

_EXPLAIN_TEMPLATE = """\
You are `ai`, a concise command-line assistant. The user ran one or more commands
in their terminal and now asks about them. Environment: {shell}.

You are given the previous command(s), their output, and exit codes, in
chronological order. Interpret the user's instruction in that context. Be brief and
direct. If you suggest a follow-up command, put it in a fenced code block tagged with
the shell name (```{shell_name}).
"""


def ask_system_prompt(shell: ShellInfo) -> str:
    return _ASK_TEMPLATE.format(shell=shell.describe(), shell_name=shell.name)


def explain_system_prompt(shell: ShellInfo) -> str:
    return _EXPLAIN_TEMPLATE.format(shell=shell.describe(), shell_name=shell.name)


def explain_user_prompt(blocks, instruction: str) -> str:
    """Render one or more command blocks (oldest first) plus the user's instruction.

    `blocks` is a sequence of objects with .cmd, .output and .exit_code attributes.
    """
    parts = []
    for i, b in enumerate(blocks, 1):
        exit_str = "unknown" if b.exit_code is None else str(b.exit_code)
        output = b.output if b.output else "(no output)"
        parts.append(
            f"Command {i} (exit code {exit_str}):\n```\n{b.cmd}\n```\n"
            f"Output:\n```\n{output}\n```"
        )
    n = len(blocks)
    header = "the previous command" if n == 1 else f"the previous {n} commands"
    return f"Here {'is' if n == 1 else 'are'} {header} and their output:\n\n" + "\n\n".join(parts) + f"\n\nInstruction: {instruction}"
