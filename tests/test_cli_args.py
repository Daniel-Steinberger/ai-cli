"""CLI dispatch: offset detection, leading options, subcommands."""

from ai_cli import cli


def test_consume_leading_model_spaced():
    model, rest = cli._consume_leading_options(["--model", "gpt-x", "hello", "world"])
    assert model == "gpt-x"
    assert rest == ["hello", "world"]


def test_consume_leading_model_equals():
    model, rest = cli._consume_leading_options(["--model=gpt-y", "-1", "explain"])
    assert model == "gpt-y"
    assert rest == ["-1", "explain"]


def test_no_leading_option():
    model, rest = cli._consume_leading_options(["how", "to", "list"])
    assert model is None
    assert rest == ["how", "to", "list"]


def test_offset_regex():
    assert cli._OFFSET.match("-1").group(1) == "1"
    assert cli._OFFSET.match("-12").group(1) == "12"
    assert cli._OFFSET.match("-x") is None
    assert cli._OFFSET.match("how") is None


def test_help_runs(capsys):
    assert cli.main(["--help"]) == 0
    assert "Ask anything" in capsys.readouterr().out
