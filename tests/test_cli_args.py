"""CLI dispatch: offset detection, option extraction, subcommands, default mode."""

from ai_cli import cli


def test_extract_model_spaced():
    opts = cli._extract_options(["--model", "gpt-x", "hello", "world"])
    assert opts.model == "gpt-x"
    assert opts.debug is False
    assert opts.print_mode is False
    assert opts.rest == ["hello", "world"]


def test_extract_model_equals():
    opts = cli._extract_options(["--model=gpt-y", "-1", "explain"])
    assert opts.model == "gpt-y"
    assert opts.rest == ["-1", "explain"]


def test_extract_debug_flag():
    opts = cli._extract_options(["--debug", "-1", "explain"])
    assert opts.debug is True
    assert opts.model is None
    assert opts.rest == ["-1", "explain"]


def test_extract_option_after_offset():
    # The reported bug: `ai -4 --debug explain` must still activate --debug.
    opts = cli._extract_options(["-4", "--debug", "explain"])
    assert opts.debug is True
    assert opts.rest == ["-4", "explain"]


def test_extract_print_flag():
    opts = cli._extract_options(["-p", "-1"])
    assert opts.print_mode is True
    assert opts.rest == ["-1"]
    opts = cli._extract_options(["--print", "hi", "there"])
    assert opts.print_mode is True
    assert opts.rest == ["hi", "there"]


def test_interactive_flag_is_a_noop_alias():
    # -i used to select chat; chat is the default now, so it must simply be ignored.
    opts = cli._extract_options(["-i", "-3", "fasse", "zusammen"])
    assert opts.print_mode is False
    assert opts.rest == ["-3", "fasse", "zusammen"]
    assert cli._extract_options(["--interactive"]).rest == []


def test_extract_print_after_offset():
    opts = cli._extract_options(["-2", "-p", "warum"])
    assert opts.print_mode is True
    assert opts.rest == ["-2", "warum"]


def test_extract_debug_and_model_any_order():
    opts = cli._extract_options(["-2", "--debug", "--model", "m", "why"])
    assert opts.debug is True
    assert opts.model == "m"
    assert opts.rest == ["-2", "why"]


def test_no_option():
    opts = cli._extract_options(["how", "to", "list"])
    assert opts.model is None
    assert opts.debug is False
    assert opts.print_mode is False
    assert opts.rest == ["how", "to", "list"]


def test_offset_regex():
    assert cli._OFFSET.match("-1").group(1) == "1"
    assert cli._OFFSET.match("-12").group(1) == "12"
    assert cli._OFFSET.match("-x") is None
    assert cli._OFFSET.match("how") is None


def test_help_runs(capsys):
    assert cli.main(["--help"]) == 0
    assert "Interactive chat" in capsys.readouterr().out


def _stub_dispatch(monkeypatch, is_terminal=True):
    """Make cli.main() see (or not see) a terminal, and record which mode it picks."""
    seen = {}

    def record(key, value):
        seen[key] = value
        return 0

    monkeypatch.setattr(cli.Console, "is_terminal", property(lambda self: is_terminal))
    monkeypatch.setattr(cli, "_read_piped_stdin", lambda: None)
    monkeypatch.setattr(cli, "load_config", lambda model_override=None: object())
    monkeypatch.setattr(cli, "_interactive",
                        lambda cfg, off, text, con, sin: record("chat", (off, text)))
    monkeypatch.setattr(cli, "_explain",
                        lambda cfg, off, instr, con, **kw: record("explain", (off, instr)))
    monkeypatch.setattr(cli.ask_mod, "ask", lambda cfg, q, con, **kw: record("ask", q))
    return seen


def test_bare_invocation_starts_chat(monkeypatch):
    seen = _stub_dispatch(monkeypatch)
    assert cli.main([]) == 0
    assert seen == {"chat": (None, "")}


def test_question_seeds_chat(monkeypatch):
    seen = _stub_dispatch(monkeypatch)
    assert cli.main(["wie", "geht", "das"]) == 0
    assert seen == {"chat": (None, "wie geht das")}


def test_offset_without_print_starts_chat(monkeypatch):
    seen = _stub_dispatch(monkeypatch)
    assert cli.main(["-2", "warum"]) == 0
    assert seen == {"chat": (2, "warum")}


def test_print_flag_asks_once(monkeypatch):
    seen = _stub_dispatch(monkeypatch)
    assert cli.main(["-p", "wie", "geht", "das"]) == 0
    assert seen == {"ask": "wie geht das"}


def test_print_flag_with_offset_explains(monkeypatch):
    seen = _stub_dispatch(monkeypatch)
    assert cli.main(["-p", "-2", "warum"]) == 0
    assert seen == {"explain": (2, "warum")}


def test_offset_defaults_to_explain_instruction(monkeypatch):
    seen = _stub_dispatch(monkeypatch)
    assert cli.main(["-p", "-1"]) == 0
    assert seen == {"explain": (1, "explain")}


def test_without_terminal_falls_back_to_print(monkeypatch):
    seen = _stub_dispatch(monkeypatch, is_terminal=False)
    assert cli.main(["wie", "geht", "das"]) == 0
    assert seen == {"ask": "wie geht das"}


def test_without_terminal_and_without_args_prints_usage(monkeypatch, capsys):
    seen = _stub_dispatch(monkeypatch, is_terminal=False)
    assert cli.main([]) == 0
    assert seen == {}
    assert "Interactive chat" in capsys.readouterr().out


def test_debug_blocks_prints_context(capsys):
    from rich.console import Console

    from ai_cli.context import CommandBlock

    blocks = [
        CommandBlock(cmd="ls -l", output="total 0", exit_code=0),
        CommandBlock(cmd="false", output="", exit_code=1),
    ]
    cli._print_debug_blocks(2, blocks, Console())
    out = capsys.readouterr().out
    assert "ls -l" in out
    assert "total 0" in out
    assert "false" in out
    assert "--debug" in out
