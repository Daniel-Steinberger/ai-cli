"""Feature 2: parse the recorded shell-session typescript into command blocks.

The fish integration (see data/ai-cli.fish) records the interactive session with
`script(1)` and emits invisible custom OSC 1337 markers around each command:

    preexec:  ESC ] 1337 ; AICMD=<base64(command)> BEL   ESC ] 1337 ; AIOUT BEL
    postexec: ESC ] 1337 ; AIEND=<exit-code> BEL

A *completed* block therefore looks like:  AICMD AIOUT <output> AIEND
The currently-running `ai` invocation has emitted AICMD+AIOUT but not yet AIEND, so
it is naturally excluded (we only finalize blocks that reach an AIEND marker).

We deliberately do NOT reuse OSC 133 (the de-facto "semantic prompt" markers),
because fish 4.x emits its own 133;A/C/D sequences, which would collide.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import log_dir

BEL = "\x07"

_MARKER = re.compile(
    r"\x1b\]1337;AICMD=(?P<cmd>[A-Za-z0-9+/=]*)\x07"
    r"|\x1b\]1337;AIOUT\x07"
    r"|\x1b\]1337;AIEND=(?P<exit>-?\d+)\x07"
)

# CSI sequences, OSC sequences (terminated by BEL or ST), and stray single-char escapes.
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_OTHER_ESC = re.compile(r"\x1b[@-Z\\-_]")


class NoSessionError(RuntimeError):
    """Raised when no active recorded session can be found."""


@dataclass
class CommandBlock:
    cmd: str
    output: str
    exit_code: int | None


def strip_ansi(text: str) -> str:
    text = _OSC.sub("", text)
    text = _CSI.sub("", text)
    text = _OTHER_ESC.sub("", text)
    # Normalize carriage returns left by terminal cursor movement.
    text = text.replace("\r\n", "\n").replace("\r", "")
    return text


def session_file() -> Path:
    """Locate the typescript for the current session, else the newest one."""
    env = os.environ.get("AI_CLI_SESSION")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    directory = log_dir()
    if directory.is_dir():
        candidates = sorted(
            directory.glob("*.typescript"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    raise NoSessionError(
        "No recorded terminal session found. Run `ai install` and restart your "
        "shell to enable reading previous commands."
    )


def _decode_cmd(b64: str) -> str:
    try:
        return base64.b64decode(b64).decode("utf-8", errors="replace").strip()
    except (binascii.Error, ValueError):
        return ""


def parse_blocks(text: str) -> list[CommandBlock]:
    """Return completed command blocks in chronological order."""
    blocks: list[CommandBlock] = []
    cur_cmd: str | None = None
    out_start: int | None = None

    for m in _MARKER.finditer(text):
        if m.group("cmd") is not None:  # AICMD -> a new command begins
            cur_cmd = _decode_cmd(m.group("cmd"))
            out_start = None
        elif m.group("exit") is not None:  # AIEND -> command finished
            if cur_cmd is not None and out_start is not None:
                output = strip_ansi(text[out_start : m.start()]).strip("\n")
                blocks.append(
                    CommandBlock(cmd=cur_cmd, output=output, exit_code=int(m.group("exit")))
                )
            cur_cmd = None
            out_start = None
        else:  # AIOUT -> output region begins
            if cur_cmd is not None:
                out_start = m.end()
    return blocks


def read_session_text(path: Path | None = None) -> str:
    path = path or session_file()
    return path.read_text(encoding="utf-8", errors="replace")


def get_blocks(n: int, *, path: Path | None = None, max_output_chars: int = 6000) -> list[CommandBlock]:
    """Return the last N completed command blocks, oldest first. `-1` -> last command,
    `-4` -> the last four. Fewer are returned if fewer were recorded."""
    if n < 1:
        raise ValueError("command offset must be >= 1")
    blocks = parse_blocks(read_session_text(path))
    if not blocks:
        raise NoSessionError(
            "No previous commands recorded yet. Run `ai install` and restart your "
            "shell, then run a command before using `ai -N`."
        )
    selected = blocks[-n:]
    for block in selected:
        if len(block.output) > max_output_chars:
            block.output = _elide(block.output, max_output_chars)
    return selected


def get_block(n: int, *, path: Path | None = None, max_output_chars: int = 6000) -> CommandBlock:
    """Return the N-th last completed command block (n>=1). n=1 is the previous command."""
    if n < 1:
        raise ValueError("command offset must be >= 1")
    blocks = parse_blocks(read_session_text(path))
    if len(blocks) < n:
        raise NoSessionError(
            f"Only {len(blocks)} previous command(s) recorded; cannot go back {n}."
        )
    block = blocks[-n]
    if len(block.output) > max_output_chars:
        block.output = _elide(block.output, max_output_chars)
    return block


def _elide(text: str, limit: int) -> str:
    half = limit // 2
    omitted = len(text) - 2 * half
    return f"{text[:half]}\n... [{omitted} characters omitted] ...\n{text[-half:]}"
