"""Detect the user's interactive shell and OS so the model can tailor answers."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class ShellInfo:
    name: str  # "fish", "zsh", "bash", "sh", or "unknown"
    version: str | None
    os: str  # e.g. "Linux", "Darwin", "Windows"

    def describe(self) -> str:
        ver = f" {self.version}" if self.version else ""
        return f"{self.name}{ver} on {self.os}"


_KNOWN = ("fish", "zsh", "bash", "sh", "pwsh", "powershell", "tcsh", "csh", "ksh", "dash")


def _normalize(raw: str | None) -> str | None:
    if not raw:
        return None
    base = os.path.basename(raw.strip()).lower()
    base = base.removesuffix(".exe")
    base = base.lstrip("-")  # login shells appear as e.g. "-bash"
    for known in _KNOWN:
        if base == known:
            return known
    return base or None


def _from_parent_process() -> str | None:
    """Best-effort: read the parent process name (Linux /proc, then `ps`)."""
    ppid = os.getppid()
    # Linux fast path.
    try:
        with open(f"/proc/{ppid}/comm", encoding="utf-8") as fh:
            return _normalize(fh.read())
    except OSError:
        pass
    # Portable fallback via ps (macOS, BSD).
    if shutil.which("ps"):
        try:
            out = subprocess.run(
                ["ps", "-o", "comm=", "-p", str(ppid)],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if out.returncode == 0:
                return _normalize(out.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _version(name: str) -> str | None:
    if not shutil.which(name):
        return None
    try:
        out = subprocess.run(
            [name, "--version"], capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr).strip()
    if not text:
        return None
    # Grab the first token that looks like a version number.
    import re

    m = re.search(r"\d+\.\d+(?:\.\d+)?", text)
    return m.group(0) if m else None


def detect_shell() -> ShellInfo:
    """Resolve the shell from (1) the integration env var, (2) parent process,
    (3) $SHELL. Always returns a populated ShellInfo (name may be 'unknown')."""
    name = (
        _normalize(os.environ.get("AI_CLI_SHELL"))
        or _from_parent_process()
        or _normalize(os.environ.get("SHELL"))
        or "unknown"
    )
    version = _version(name) if name != "unknown" else None
    return ShellInfo(name=name, version=version, os=platform.system() or "unknown")
