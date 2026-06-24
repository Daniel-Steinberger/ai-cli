"""Parser tests for Feature 2 against a synthetic typescript with OSC markers."""

import base64

import pytest

from ai_cli.context import get_block, parse_blocks, strip_ansi


def _block(cmd: str, output: str, exit_code: int) -> str:
    b64 = base64.b64encode(cmd.encode()).decode()
    return (
        f"\x1b]1337;AICMD={b64}\x07\x1b]133;C\x07"
        f"{output}"
        f"\x1b]133;D;{exit_code}\x07"
    )


def _session(*blocks: str, trailing: str = "") -> str:
    return "Script started on ...\n" + "prompt> ".join(("", *blocks)) + trailing


def test_parse_two_blocks():
    text = _session(
        _block("ls -l", "total 0\n", 0),
        _block("cat missing", "cat: missing: No such file or directory\n", 1),
    )
    blocks = parse_blocks(text)
    assert len(blocks) == 2
    assert blocks[0].cmd == "ls -l"
    assert blocks[0].output == "total 0"
    assert blocks[0].exit_code == 0
    assert blocks[1].cmd == "cat missing"
    assert blocks[1].exit_code == 1


def test_incomplete_trailing_block_excluded():
    # The currently-running `ai` command has AICMD+C but no D yet.
    b64 = base64.b64encode(b"ai -1 explain").decode()
    text = _session(_block("ls -l", "total 0\n", 0)) + (
        f"\x1b]1337;AICMD={b64}\x07\x1b]133;C\x07"
    )
    blocks = parse_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].cmd == "ls -l"


def test_get_block_offsets():
    text = _session(
        _block("first", "a\n", 0),
        _block("second", "b\n", 0),
        _block("third", "c\n", 0),
    )
    import ai_cli.context as ctx

    # Patch read to use our in-memory text.
    blocks = parse_blocks(text)
    assert blocks[-1].cmd == "third"

    monkey = lambda path=None: text  # noqa: E731
    ctx.read_session_text = monkey  # type: ignore[assignment]
    assert get_block(1).cmd == "third"
    assert get_block(2).cmd == "second"
    with pytest.raises(Exception):
        get_block(99)


def test_strip_ansi_removes_colors_and_osc():
    raw = "\x1b[31mred\x1b[0m\x1b]0;title\x07 text\r\nline\r"
    assert strip_ansi(raw) == "red text\nline"
