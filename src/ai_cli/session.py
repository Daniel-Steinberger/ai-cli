"""State of one interactive chat session.

Lives in its own module so that `chat` (the loop) and `commands` (the slash
commands that mutate the session) can both use it without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console

from .config import Config
from .shell import ShellInfo


@dataclass
class ChatSession:
    config: Config
    console: Console
    shell: ShellInfo
    # System prompt, including any context sections appended so far.
    system: str
    # Human-readable notes about the loaded context, shown in the banner.
    notes: list[str] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.messages:
            self.reset()

    def reset(self) -> None:
        """Drop the conversation. The system prompt (and thus any loaded context)
        stays — `/clear` is about the dialogue, not about the session's setup."""
        self.messages = [{"role": "system", "content": self.system}]

    def add_context(self, section: str, note: str) -> None:
        """Append a context section to the system prompt, in place for the running
        conversation as well as for everything created by a later `reset()`."""
        self.system += section
        self.messages[0]["content"] = self.system
        self.notes.append(note)
