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
You are `ai`, a concise command-line assistant. The user ran a command in their
terminal and now asks about it. Environment: {shell}.

You are given the previous command, its output, and its exit code. Interpret the
user's instruction in that context. Be brief and direct. If you suggest a follow-up
command, put it in a fenced code block tagged with the shell name (```{shell_name}).
"""


def ask_system_prompt(shell: ShellInfo) -> str:
    return _ASK_TEMPLATE.format(shell=shell.describe(), shell_name=shell.name)


def explain_system_prompt(shell: ShellInfo) -> str:
    return _EXPLAIN_TEMPLATE.format(shell=shell.describe(), shell_name=shell.name)


def explain_user_prompt(cmd: str, output: str, exit_code: int | None, instruction: str) -> str:
    exit_str = "unknown" if exit_code is None else str(exit_code)
    return (
        f"Previous command:\n```\n{cmd}\n```\n\n"
        f"Output (exit code {exit_str}):\n```\n{output}\n```\n\n"
        f"Instruction: {instruction}"
    )
