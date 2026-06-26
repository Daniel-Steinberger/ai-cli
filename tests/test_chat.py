"""Tests for interactive chat: exit detection, the turn loop, and feed-back."""

from types import SimpleNamespace

from rich.console import Console

from ai_cli import chat as chat_mod
from ai_cli.context import CommandBlock
from ai_cli.prompts import command_result_message, format_blocks
from ai_cli.shell import ShellInfo

SHELL = ShellInfo(name="bash", version="5", os="Linux")
CFG = SimpleNamespace(model="test-model")


def _console():
    return Console(force_terminal=True)


def _feed(console, monkeypatch, lines):
    """Make console.input() yield `lines` then raise EOFError (like ^D), and present
    stdin as an interactive terminal so chat() reads via console.input."""
    it = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(console, "input", fake_input)
    monkeypatch.setattr(chat_mod.sys, "stdin", SimpleNamespace(isatty=lambda: True))


def test_is_exit():
    for word in ["exit", "quit", "bye", "q", ":q", "EXIT", "  bye  "]:
        assert chat_mod.is_exit(word)
    assert not chat_mod.is_exit("hello")
    assert not chat_mod.is_exit("explain this")


def test_chat_basic_loop(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, ["hallo", "exit"])

    calls = []
    monkeypatch.setattr(chat_mod, "_setup_readline", lambda: None)
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: calls.append([m["role"] for m in messages]) or "hi")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    rc = chat_mod.chat(CFG, console, SHELL)
    assert rc == 0
    # "hallo" -> one model call; "exit" quits without a call.
    assert len(calls) == 1
    assert calls[0] == ["system", "user"]


def test_chat_feeds_command_output_back(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, ["list files"])  # then EOF ends the session

    rendered = []
    answers = iter(["run ```bash\nls\n```", "those are your files"])
    monkeypatch.setattr(chat_mod, "_setup_readline", lambda: None)
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: rendered.append([dict(m) for m in messages]) or next(answers))

    captures = iter([("ls", "file1\nfile2", 0)])
    monkeypatch.setattr(chat_mod, "offer_to_run_capture",
                        lambda answer, shell, con: next(captures, None))

    rc = chat_mod.chat(CFG, console, SHELL)
    assert rc == 0
    # First answer suggests a command -> it runs -> output fed back -> second render.
    assert len(rendered) == 2
    second_turn_users = [m["content"] for m in rendered[1] if m["role"] == "user"]
    assert any("I ran that command" in c and "file1" in c for c in second_turn_users)


def test_chat_initial_text_is_first_turn(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, [])  # immediate EOF after the seeded turn

    calls = []
    monkeypatch.setattr(chat_mod, "_setup_readline", lambda: None)
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: calls.append(messages[-1]["content"]) or "ok")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    chat_mod.chat(CFG, console, SHELL, initial_text="warum?")
    assert calls == ["warum?"]


def test_format_blocks_and_result_message():
    blocks = [CommandBlock(cmd="ls -l", output="total 0", exit_code=0)]
    fb = format_blocks(blocks)
    assert "ls -l" in fb and "total 0" in fb

    msg = command_result_message("whoami", "dst", 0)
    assert "whoami" in msg and "dst" in msg and "code 0" in msg
