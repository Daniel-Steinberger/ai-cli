"""Slash commands: parsing, completion, and the individual handlers."""

from types import SimpleNamespace

import pytest
from rich.console import Console

from ai_cli import commands
from ai_cli.context import CommandBlock, NoSessionError
from ai_cli.session import ChatSession


def _session():
    return ChatSession(
        config=SimpleNamespace(model="test-model", api_key="k", base_url="http://x/v1",
                               sources={"model": "default"}),
        console=Console(force_terminal=True),
        shell=SimpleNamespace(name="bash"),
        system="SYSTEM",
    )


def test_split_known_command():
    cmd, args = commands.split("/clear")
    assert cmd.name == "/clear"
    assert args == ""
    cmd, args = commands.split("  /model gpt-x  ")
    assert cmd.name == "/model"
    assert args == "gpt-x"


def test_split_unknown_or_plain_text_is_none():
    # Not a command -> must reach the model as an ordinary question.
    assert commands.split("/tmp/foo — was ist das?") is None
    assert commands.split("wie geht das?") is None
    assert commands.split("/") is None
    assert commands.split("") is None


def test_completions_filter_by_prefix():
    assert [c.name for c in commands.completions("/cl")] == ["/clear"]
    assert [c.name for c in commands.completions("/co")] == ["/context", "/config"]
    assert commands.completions("/zzz") == []
    assert len(commands.completions("/")) == len(commands.COMMANDS)


def test_every_command_is_listed_with_a_description():
    for cmd in commands.COMMANDS:
        assert cmd.name.startswith("/")
        assert cmd.usage.startswith(cmd.name)
        assert cmd.description


def test_clear_resets_history_keeps_system():
    session = _session()
    session.messages.append({"role": "user", "content": "hallo"})
    assert commands.dispatch(session, "/clear") is True
    assert session.messages == [{"role": "system", "content": "SYSTEM"}]


def test_exit_returns_false():
    assert commands.dispatch(_session(), "/exit") is False


def test_model_shows_and_switches():
    session = _session()
    commands.dispatch(session, "/model")
    assert session.config.model == "test-model"
    commands.dispatch(session, "/model gpt-neu")
    assert session.config.model == "gpt-neu"
    assert session.config.sources["model"] == "chat"


def test_help_lists_all_commands_with_usage(capsys):
    commands.dispatch(_session(), "/help")
    out = capsys.readouterr().out
    for cmd in commands.COMMANDS:
        # The full usage must survive: "[name]" would be eaten as Rich markup.
        assert cmd.usage in out
        assert cmd.description in out


def test_context_usage_hint_survives_markup(capsys):
    commands.dispatch(_session(), "/context nope")
    assert "/context [-N]" in capsys.readouterr().out


def test_config_shows_the_table(capsys):
    commands.dispatch(_session(), "/config")
    out = capsys.readouterr().out
    assert "test-model" in out
    assert "base_url" in out


def test_context_loads_blocks(monkeypatch):
    session = _session()
    monkeypatch.setattr(commands, "get_blocks",
                        lambda n: [CommandBlock(cmd=f"cmd{i}", output="out", exit_code=0)
                                   for i in range(n)])
    assert commands.dispatch(session, "/context -2") is True
    assert "cmd0" in session.system and "cmd1" in session.system
    # Also present for the running conversation and after a reset.
    assert "cmd0" in session.messages[0]["content"]
    session.reset()
    assert "cmd0" in session.messages[0]["content"]
    assert session.notes == ["the last 2 command(s)"]


def test_context_defaults_to_one_and_accepts_plain_number(monkeypatch):
    seen = []
    monkeypatch.setattr(commands, "get_blocks",
                        lambda n: seen.append(n) or [CommandBlock(cmd="c", output="", exit_code=0)])
    commands.dispatch(_session(), "/context")
    commands.dispatch(_session(), "/context 3")
    assert seen == [1, 3]


def test_context_without_recording_is_not_fatal(monkeypatch, capsys):
    session = _session()

    def boom(n):
        raise NoSessionError("no recorded session")

    monkeypatch.setattr(commands, "get_blocks", boom)
    assert commands.dispatch(session, "/context") is True
    assert "no recorded session" in capsys.readouterr().out
    assert session.notes == []


@pytest.mark.parametrize("args", ["x", "-0", "abc"])
def test_context_rejects_bad_argument(args, capsys):
    assert commands.dispatch(_session(), f"/context {args}") is True
    assert "Usage:" in capsys.readouterr().out
