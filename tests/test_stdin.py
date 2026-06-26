"""Piped stdin: append_stdin formatting and the cli stdin reader."""

import io

from ai_cli import cli
from ai_cli.prompts import append_stdin


def test_append_stdin_with_question():
    out = append_stdin("translate to german", "Hello world")
    assert "translate to german" in out
    assert "Hello world" in out
    assert "stdin" in out.lower()


def test_append_stdin_without_question():
    # No instruction -> the piped text is the prompt itself (still wrapped).
    out = append_stdin("", "just this")
    assert "just this" in out


def test_append_stdin_none_is_noop():
    assert append_stdin("hello", None) == "hello"
    assert append_stdin("hello", "") == "hello"


class _PipedStdin(io.StringIO):
    def isatty(self):
        return False


class _TtyStdin(io.StringIO):
    def isatty(self):
        return True


def test_read_piped_stdin(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", _PipedStdin("piped data\n"))
    assert cli._read_piped_stdin() == "piped data"


def test_read_piped_stdin_tty_returns_none(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", _TtyStdin("ignored"))
    assert cli._read_piped_stdin() is None


def test_read_piped_stdin_empty_returns_none(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", _PipedStdin("   \n"))
    assert cli._read_piped_stdin() is None
