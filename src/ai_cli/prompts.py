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

_CHAT_TEMPLATE = """\
You are `ai`, a helpful, concise command-line assistant in an interactive chat.
Environment: {shell}.

- Be brief and direct; this is a terminal conversation.
- When you propose a command for the user to run, put it in a fenced code block
  tagged with the shell name (```{shell_name}), containing only the runnable
  command(s). The user will be asked whether to run it, and its output will be fed
  back to you so you can react to the actual result.
- Any command MUST be valid for this shell ({shell_name}) and OS. Do not invent flags.
"""


def ask_system_prompt(shell: ShellInfo) -> str:
    return _ASK_TEMPLATE.format(shell=shell.describe(), shell_name=shell.name)


def explain_system_prompt(shell: ShellInfo) -> str:
    return _EXPLAIN_TEMPLATE.format(shell=shell.describe(), shell_name=shell.name)


def chat_system_prompt(shell: ShellInfo) -> str:
    return _CHAT_TEMPLATE.format(shell=shell.describe(), shell_name=shell.name)


def format_blocks(blocks) -> str:
    """Render one or more command blocks (oldest first) as text.

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
    return "\n\n".join(parts)


def explain_user_prompt(blocks, instruction: str) -> str:
    n = len(blocks)
    header = "the previous command" if n == 1 else f"the previous {n} commands"
    return (
        f"Here {'is' if n == 1 else 'are'} {header} and their output:\n\n"
        f"{format_blocks(blocks)}\n\nInstruction: {instruction}"
    )


def chat_context_message(blocks) -> str:
    """Initial context block injected into the chat system prompt."""
    n = len(blocks)
    header = "the previous command" if n == 1 else f"the previous {n} commands"
    return (
        f"\nFor context, here {'is' if n == 1 else 'are'} {header} the user just ran, "
        f"with output:\n\n{format_blocks(blocks)}\n"
    )


def append_stdin(text: str, stdin_text: str | None) -> str:
    """Combine a question/instruction with text piped in via stdin.

    `echo foo | ai "translate"` -> the piped text is attached as input below the
    instruction. With no instruction, the piped text becomes the prompt itself.
    """
    if not stdin_text:
        return text
    block = f"Input (piped via stdin):\n```\n{stdin_text}\n```"
    if text:
        return f"{text}\n\n{block}"
    return block


def stdin_context_message(stdin_text: str) -> str:
    """Context section appended to the chat system prompt for piped input."""
    return f"\nThe user piped this input into the chat:\n```\n{stdin_text}\n```\n"


def command_result_message(cmd: str, output: str, exit_code: int | None) -> str:
    """A user-role message reporting the result of a command the assistant suggested."""
    exit_str = "unknown" if exit_code is None else str(exit_code)
    body = output if output.strip() else "(no output)"
    return (
        f"I ran that command:\n```\n{cmd}\n```\n"
        f"It exited with code {exit_str}. Output:\n```\n{body}\n```"
    )
