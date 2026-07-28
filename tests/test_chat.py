"""Tests for interactive chat: exit detection, the turn loop, and feed-back."""

from types import SimpleNamespace

from rich.console import Console

from ai_cli import chat as chat_mod
from ai_cli.context import CommandBlock
from ai_cli.prompts import command_result_message, format_blocks
from ai_cli.shell import ShellInfo

SHELL = ShellInfo(name="bash", version="5", os="Linux")


def _cfg():
    return SimpleNamespace(model="test-model", api_key="k",
                           base_url="http://x/v1", sources={"model": "default"})


def _console():
    return Console(force_terminal=True)


def _feed(console, monkeypatch, lines):
    """Make the chat's line reader yield `lines` and then raise EOFError (like ^D),
    and present stdin as an interactive terminal."""
    it = iter(lines)

    class _Reader:
        def read(self):
            try:
                return next(it)
            except StopIteration:
                raise EOFError

        def close(self):
            pass

    monkeypatch.setattr(chat_mod, "_build_input", lambda con: _Reader())
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
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: calls.append([m["role"] for m in messages]) or "hi")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    rc = chat_mod.chat(_cfg(), console, SHELL)
    assert rc == 0
    # "hallo" -> one model call; "exit" quits without a call.
    assert len(calls) == 1
    assert calls[0] == ["system", "user"]


def test_chat_feeds_command_output_back(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, ["list files"])  # then EOF ends the session

    rendered = []
    answers = iter(["run ```bash\nls\n```", "those are your files"])
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: rendered.append([dict(m) for m in messages]) or next(answers))

    captures = iter([("ls", "file1\nfile2", 0)])
    monkeypatch.setattr(chat_mod, "offer_to_run_capture",
                        lambda answer, shell, con: next(captures, None))

    rc = chat_mod.chat(_cfg(), console, SHELL)
    assert rc == 0
    # First answer suggests a command -> it runs -> output fed back -> second render.
    assert len(rendered) == 2
    second_turn_users = [m["content"] for m in rendered[1] if m["role"] == "user"]
    assert any("I ran that command" in c and "file1" in c for c in second_turn_users)


def test_chat_initial_text_is_first_turn(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, [])  # immediate EOF after the seeded turn

    calls = []
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: calls.append(messages[-1]["content"]) or "ok")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    chat_mod.chat(_cfg(), console, SHELL, initial_text="warum?")
    assert calls == ["warum?"]


def test_slash_clear_drops_history_but_not_context(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, ["hallo", "/clear", "und jetzt?"])

    rendered = []
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: rendered.append([dict(m) for m in messages]) or "ok")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    blocks = [CommandBlock(cmd="ls -l", output="total 0", exit_code=0)]
    chat_mod.chat(_cfg(), console, SHELL, blocks=blocks)

    # Second turn starts from scratch again: system + the new user message only …
    assert [m["role"] for m in rendered[1]] == ["system", "user"]
    assert rendered[1][-1]["content"] == "und jetzt?"
    # … but the command context is still part of the system prompt.
    assert "ls -l" in rendered[1][0]["content"]


def test_slash_exit_ends_the_chat(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, ["/exit", "never asked"])

    calls = []
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: calls.append(1) or "ok")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    assert chat_mod.chat(_cfg(), console, SHELL) == 0
    assert calls == []


def test_unknown_slash_input_goes_to_the_model(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, ["/tmp/foo — was ist das?"])

    calls = []
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: calls.append(messages[-1]["content"]) or "ok")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    chat_mod.chat(_cfg(), console, SHELL)
    assert calls == ["/tmp/foo — was ist das?"]


def test_slash_model_switches_model(monkeypatch):
    console = _console()
    _feed(console, monkeypatch, ["/model gpt-neu", "frage"])

    used = []
    monkeypatch.setattr(chat_mod, "render_stream",
                        lambda cfg, messages, con: used.append(cfg.model) or "ok")
    monkeypatch.setattr(chat_mod, "offer_to_run_capture", lambda *a, **k: None)

    chat_mod.chat(_cfg(), console, SHELL)
    assert used == ["gpt-neu"]


def test_format_blocks_and_result_message():
    blocks = [CommandBlock(cmd="ls -l", output="total 0", exit_code=0)]
    fb = format_blocks(blocks)
    assert "ls -l" in fb and "total 0" in fb

    msg = command_result_message("whoami", "dst", 0)
    assert "whoami" in msg and "dst" in msg and "code 0" in msg
