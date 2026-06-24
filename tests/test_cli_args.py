"""CLI dispatch: offset detection, leading options, subcommands."""

from ai_cli import cli


def test_consume_leading_model_spaced():
    model, debug, rest = cli._consume_leading_options(["--model", "gpt-x", "hello", "world"])
    assert model == "gpt-x"
    assert debug is False
    assert rest == ["hello", "world"]


def test_consume_leading_model_equals():
    model, debug, rest = cli._consume_leading_options(["--model=gpt-y", "-1", "explain"])
    assert model == "gpt-y"
    assert rest == ["-1", "explain"]


def test_consume_debug_flag():
    model, debug, rest = cli._consume_leading_options(["--debug", "-1", "explain"])
    assert debug is True
    assert model is None
    assert rest == ["-1", "explain"]


def test_consume_debug_and_model_any_order():
    model, debug, rest = cli._consume_leading_options(["--debug", "--model", "m", "-2", "why"])
    assert debug is True
    assert model == "m"
    assert rest == ["-2", "why"]


def test_no_leading_option():
    model, debug, rest = cli._consume_leading_options(["how", "to", "list"])
    assert model is None
    assert debug is False
    assert rest == ["how", "to", "list"]


def test_offset_regex():
    assert cli._OFFSET.match("-1").group(1) == "1"
    assert cli._OFFSET.match("-12").group(1) == "12"
    assert cli._OFFSET.match("-x") is None
    assert cli._OFFSET.match("how") is None


def test_help_runs(capsys):
    assert cli.main(["--help"]) == 0
    assert "Ask anything" in capsys.readouterr().out


def test_debug_block_prints_context(capsys):
    from rich.console import Console

    from ai_cli.context import CommandBlock

    block = CommandBlock(cmd="ls -l", output="total 0", exit_code=0)
    cli._print_debug_block(1, block, Console())
    out = capsys.readouterr().out
    assert "ls -l" in out
    assert "total 0" in out
    assert "--debug" in out
