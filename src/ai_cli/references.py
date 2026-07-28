"""`@path` references: pull files and directories into a message as context.

`@` only starts a reference at the beginning of a token, so email addresses and
decorators (`foo@bar.com`, `@property` inside a sentence) are left alone unless
they actually resolve to something on disk. Quoted forms (`@"my file.txt"`) cover
paths with spaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .prompts import references_message

# @"quoted path" | @'quoted path' | @bare/path — only at the start of a token
# (whitespace or an opening bracket/quote before it), so `foo@bar.com` is never one.
_REF_RE = re.compile(r"""(?:^|(?<=[\s([{<"']))@(?:"([^"]+)"|'([^']+)'|([^\s"']+))""")

# Trailing punctuation is usually sentence punctuation, not part of the path.
_TRAILING = ".,;:!?)]}>\"'"

MAX_BYTES = 100_000  # per file
MAX_FILES = 10  # per message
MAX_ENTRIES = 200  # per directory listing


@dataclass
class Reference:
    raw: str  # the path as typed
    path: Path | None  # resolved path, None when nothing matched
    kind: str  # "file" | "dir" | "binary" | "missing" | "skipped" | "error"
    body: str = ""  # what is sent to the model
    note: str = ""  # short status shown to the user

    @property
    def usable(self) -> bool:
        return self.kind in ("file", "dir")


def _human(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _candidates(raw: str):
    """The path as typed, then progressively without trailing punctuation."""
    yield raw
    trimmed = raw
    while trimmed and trimmed[-1] in _TRAILING:
        trimmed = trimmed[:-1]
        if trimmed:
            yield trimmed


def _locate(raw: str, cwd: Path) -> tuple[str, Path | None]:
    """Return (matched text, existing path) — path is None if nothing exists."""
    for candidate in _candidates(raw):
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = cwd / path
        if path.exists():
            return candidate, path
    return raw, None


def _read_file(path: Path) -> tuple[str, str, str]:
    """Return (kind, body, note) for a regular file."""
    try:
        size = path.stat().st_size
        raw = path.read_bytes()[:MAX_BYTES]
    except OSError as exc:
        return "error", "", f"unreadable ({exc.strerror or exc})"
    if b"\0" in raw:
        return "binary", "", f"binary, {_human(size)} — not included"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", "replace")
    note = _human(size)
    if size > MAX_BYTES:
        text += f"\n… [truncated at {_human(MAX_BYTES)} of {_human(size)}]"
        note += f", truncated at {_human(MAX_BYTES)}"
    return "file", text, note


def _read_dir(path: Path) -> tuple[str, str, str]:
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    except OSError as exc:
        return "error", "", f"unreadable ({exc.strerror or exc})"
    total = len(entries)
    shown = entries[:MAX_ENTRIES]
    lines = [f"{e.name}/" if e.is_dir() else e.name for e in shown]
    note = f"{total} entr{'y' if total == 1 else 'ies'}"
    if total > len(shown):
        lines.append(f"… [{total - len(shown)} more]")
        note += f", first {len(shown)} listed"
    return "dir", "\n".join(lines), note


def find(text: str, cwd: Path | None = None) -> list[Reference]:
    """Resolve every `@path` in `text`, reading files and listing directories.

    Duplicates (same resolved path) are collapsed; beyond MAX_FILES the rest is
    reported as skipped rather than silently dropped.
    """
    base = cwd or Path.cwd()
    refs: list[Reference] = []
    seen: set[str] = set()
    loaded = 0

    for match in _REF_RE.finditer(text):
        raw = match.group(1) or match.group(2) or match.group(3)
        matched, path = _locate(raw, base)
        if path is None:
            refs.append(Reference(raw=raw, path=None, kind="missing", note="not found"))
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        if loaded >= MAX_FILES:
            refs.append(Reference(raw=matched, path=path, kind="skipped",
                                  note=f"skipped, more than {MAX_FILES} references"))
            continue
        kind, body, note = _read_dir(path) if path.is_dir() else _read_file(path)
        refs.append(Reference(raw=matched, path=path, kind=kind, body=body, note=note))
        if kind in ("file", "dir"):
            loaded += 1
    return refs


def display_path(path: Path, cwd: Path | None = None) -> str:
    """Path relative to the working directory when it is below it, else absolute."""
    base = cwd or Path.cwd()
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def context_block(refs: list[Reference], cwd: Path | None = None) -> str:
    """The section appended to the user message, or "" when nothing is usable."""
    usable = [r for r in refs if r.usable]
    if not usable:
        return ""
    parts = []
    for ref in usable:
        label = display_path(ref.path, cwd)
        header = f"Directory `{label}` ({ref.note}):" if ref.kind == "dir" else \
                 f"File `{label}` ({ref.note}):"
        parts.append(f"{header}\n```\n{ref.body}\n```")
    return "\n\n".join(parts)


def expand(text: str, console=None, cwd: Path | None = None) -> str:
    """Resolve `@path` references in `text` and append their content as context.

    Reports what was attached (and what was not) on `console`, so it is never a
    surprise which files were sent. Returns `text` unchanged when nothing resolved.
    """
    refs = find(text, cwd)
    if not refs:
        return text
    attached = [r for r in refs if r.usable]
    rejected = [r for r in refs if not r.usable]
    if console is not None:
        if attached:
            console.print(f"[dim]attached: {summary(attached, cwd)}[/dim]", highlight=False)
        if rejected:
            console.print(f"[yellow]not attached:[/yellow] {summary(rejected, cwd)}",
                          highlight=False)
    block = context_block(refs, cwd)
    return text + references_message(block) if block else text


def summary(refs: list[Reference], cwd: Path | None = None) -> str:
    """One-line status for the terminal, e.g. "@cli.py (4.2 KiB), @src/ (6 entries)"."""
    parts = []
    for ref in refs:
        label = display_path(ref.path, cwd) if ref.path else ref.raw
        parts.append(f"@{label} ({ref.note})" if ref.note else f"@{label}")
    return ", ".join(parts)
