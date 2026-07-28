"""The prompt_toolkit input layer: slash-command completion and its metadata."""

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.document import Document  # noqa: E402
from prompt_toolkit.input import create_pipe_input  # noqa: E402
from prompt_toolkit.output import DummyOutput  # noqa: E402

from ai_cli import chat as chat_mod  # noqa: E402


def _completions(text):
    completer = chat_mod._chat_completer()
    return list(completer.get_completions(Document(text, len(text)), None))


def test_slash_offers_all_commands_with_descriptions():
    from ai_cli import commands

    got = _completions("/")
    assert [c.text for c in got] == [cmd.name for cmd in commands.COMMANDS]
    # Every entry carries a usage hint and a description (the omnibar's meta column).
    for completion, cmd in zip(got, commands.COMMANDS):
        assert cmd.usage in completion.display[0][1]
        assert cmd.description in completion.display_meta[0][1]


def test_prefix_narrows_the_menu():
    assert [c.text for c in _completions("/cl")] == ["/clear"]
    assert [c.text for c in _completions("/co")] == ["/context", "/config"]
    assert _completions("/zz") == []


def test_no_menu_for_plain_text_or_arguments():
    assert _completions("wie geht das") == []
    # Once arguments start, the command name is settled — no popup any more.
    assert _completions("/model gpt") == []
    # A slash later in the line is a path, not a command.
    assert _completions("was ist /usr") == []


def test_current_token():
    assert chat_mod._current_token("") == ""
    assert chat_mod._current_token("/cl") == "/cl"
    assert chat_mod._current_token("erklär @src/ai") == "@src/ai"
    assert chat_mod._current_token("erklär @src/ai ") == ""


def test_at_completes_paths(tmp_path, monkeypatch):
    (tmp_path / "hello.py").write_text("x")
    (tmp_path / "helm").mkdir()
    (tmp_path / "other.txt").write_text("x")
    monkeypatch.chdir(tmp_path)

    got = {c.display[0][1]: c.display_meta[0][1] for c in _completions("erklär mir @hel")}
    assert got == {"hello.py": "file", "helm/": "directory"}
    # Directories get a trailing separator inserted so the next segment completes.
    inserted = {c.display[0][1]: c.text for c in _completions("erklär mir @hel")}
    assert inserted == {"hello.py": "lo.py", "helm/": "m/"}


def test_at_completion_inserts_only_the_missing_part(tmp_path, monkeypatch):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.txt").write_text("x")
    monkeypatch.chdir(tmp_path)

    (completion,) = _completions("@sub/de")
    # "@sub/de" stays, only the remainder is inserted.
    assert completion.text == "ep.txt"
    assert completion.display[0][1] == "deep.txt"


def _read_with_input(keys: str) -> str:
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        reader = chat_mod._PromptToolkitReader(input=pipe, output=DummyOutput())
        return reader.read()


def test_plain_input_is_returned_unchanged():
    # End-to-end through a real PromptSession (piped keys, dummy output). Tab
    # completion itself is not exercised here: with complete_while_typing the
    # candidates are computed asynchronously, so piped keys race the completion
    # task. The popup/Tab behaviour is covered by the completer tests above.
    assert _read_with_input("wie geht das?\r") == "wie geht das?"


def test_accepted_line_may_be_a_command():
    assert _read_with_input("/clear\r") == "/clear"
