"""CLI dispatch: offset detection, option extraction, subcommands."""

from ai_cli import cli


def test_extract_model_spaced():
    model, debug, interactive, rest = cli._extract_options(["--model", "gpt-x", "hello", "world"])
    assert model == "gpt-x"
    assert debug is False
    assert interactive is False
    assert rest == ["hello", "world"]


def test_extract_model_equals():
    model, debug, interactive, rest = cli._extract_options(["--model=gpt-y", "-1", "explain"])
    assert model == "gpt-y"
    assert rest == ["-1", "explain"]


def test_extract_debug_flag():
    model, debug, interactive, rest = cli._extract_options(["--debug", "-1", "explain"])
    assert debug is True
    assert model is None
    assert rest == ["-1", "explain"]


def test_extract_option_after_offset():
    # The reported bug: `ai -4 --debug explain` must still activate --debug.
    model, debug, interactive, rest = cli._extract_options(["-4", "--debug", "explain"])
    assert debug is True
    assert rest == ["-4", "explain"]


def test_extract_interactive_flag():
    model, debug, interactive, rest = cli._extract_options(["-i", "-1"])
    assert interactive is True
    assert rest == ["-1"]
    model, debug, interactive, rest = cli._extract_options(["--interactive", "hi", "there"])
    assert interactive is True
    assert rest == ["hi", "there"]


def test_extract_interactive_with_offset_and_text_any_order():
    model, debug, interactive, rest = cli._extract_options(["-3", "-i", "fasse", "zusammen"])
    assert interactive is True
    assert rest == ["-3", "fasse", "zusammen"]


def test_extract_debug_and_model_any_order():
    model, debug, interactive, rest = cli._extract_options(["-2", "--debug", "--model", "m", "why"])
    assert debug is True
    assert model == "m"
    assert rest == ["-2", "why"]


def test_no_option():
    model, debug, interactive, rest = cli._extract_options(["how", "to", "list"])
    assert model is None
    assert debug is False
    assert interactive is False
    assert rest == ["how", "to", "list"]


def test_offset_regex():
    assert cli._OFFSET.match("-1").group(1) == "1"
    assert cli._OFFSET.match("-12").group(1) == "12"
    assert cli._OFFSET.match("-x") is None
    assert cli._OFFSET.match("how") is None


def test_help_runs(capsys):
    assert cli.main(["--help"]) == 0
    assert "Ask anything" in capsys.readouterr().out


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
