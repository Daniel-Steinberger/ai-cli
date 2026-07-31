"""Parser tests for Feature 2 against a synthetic typescript with OSC markers."""

import base64

import pytest

from ai_cli.context import get_blocks, parse_blocks, strip_ansi

# Fish 4.x emits its own OSC 133 markers; the parser must ignore them and rely
# only on our custom OSC 1337 AICMD/AIOUT/AIEND markers.
FISH_NATIVE = "\x1b]133;A\x07\x1b]133;C\x07\x1b]133;D;0\x07"


def _block(cmd: str, output: str, exit_code: int) -> str:
    b64 = base64.b64encode(cmd.encode()).decode()
    return (
        f"\x1b]1337;AICMD={b64}\x07\x1b]1337;AIOUT\x07"
        f"{output}"
        f"\x1b]1337;AIEND={exit_code}\x07"
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


def test_native_fish_133_markers_are_ignored():
    # Interleave fish's native 133 markers around our 1337 markers.
    b64 = base64.b64encode(b"ls -l").decode()
    text = _session() + (
        FISH_NATIVE
        + f"\x1b]1337;AICMD={b64}\x07\x1b]1337;AIOUT\x07"
        + "\x1b]133;C\x07total 0\n"  # a stray native marker inside the output
        + "\x1b]1337;AIEND=0\x07"
        + "\x1b]133;D;0\x07"
    )
    blocks = parse_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].cmd == "ls -l"
    assert blocks[0].output == "total 0"
    assert blocks[0].exit_code == 0


def test_incomplete_trailing_block_excluded():
    # The currently-running `ai` command has AICMD+AIOUT but no AIEND yet.
    b64 = base64.b64encode(b"ai -1 explain").decode()
    text = _session(_block("ls -l", "total 0\n", 0)) + (
        f"\x1b]1337;AICMD={b64}\x07\x1b]1337;AIOUT\x07"
    )
    blocks = parse_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].cmd == "ls -l"


def test_get_blocks_returns_last_n(monkeypatch):
    text = _session(
        _block("first", "a\n", 0),
        _block("second", "b\n", 0),
        _block("third", "c\n", 0),
    )
    import ai_cli.context as ctx

    monkeypatch.setattr(ctx, "read_session_text", lambda path=None: text)

    # -1 -> just the previous command.
    one = get_blocks(1)
    assert [b.cmd for b in one] == ["third"]

    # -2 -> last two, oldest first.
    two = get_blocks(2)
    assert [b.cmd for b in two] == ["second", "third"]

    # Asking for more than exist returns all available, no error.
    allb = get_blocks(99)
    assert [b.cmd for b in allb] == ["first", "second", "third"]


def test_get_blocks_no_session(monkeypatch):
    import ai_cli.context as ctx

    monkeypatch.setattr(ctx, "read_session_text", lambda path=None: "no markers here")
    with pytest.raises(ctx.NoSessionError):
        get_blocks(1)


def _write_session(tmp_path, monkeypatch, text: str, *, prefix: bytes = b""):
    """Write a typescript and point AI_CLI_SESSION at it."""
    path = tmp_path / "s.typescript"
    path.write_bytes(prefix + text.encode())
    monkeypatch.setenv("AI_CLI_SESSION", str(path))
    return path


def test_only_the_tail_is_read(tmp_path, monkeypatch):
    """A huge recording must never be loaded whole (that raised MemoryError)."""
    import ai_cli.context as ctx

    flood = "\x1b[64;185H " * 200_000  # ~1.4 MB of full-screen redraws
    text = _session(_block("older", "x\n", 0)) + flood + _block("newest", "done\n", 0)
    path = _write_session(tmp_path, monkeypatch, text)

    read = ctx.read_session_text(path, window=64 * 1024)
    assert len(read) < len(text)  # only a window, not the whole file
    assert [b.cmd for b in parse_blocks(read)] == ["newest"]

    # The full pipeline picks the newest command out of the flood.
    assert [b.cmd for b in get_blocks(1, path=path)] == ["newest"]


def test_window_grows_until_a_finished_command_is_found(tmp_path, monkeypatch):
    import ai_cli.context as ctx

    # The last command sits ~1 MB back, far outside the initial 4 KiB window.
    text = _session(_block("wanted", "out\n", 0)) + "noise " * 200_000
    path = _write_session(tmp_path, monkeypatch, text)

    read = ctx.read_session_text(path, window=4096)
    assert [b.cmd for b in parse_blocks(read)] == ["wanted"]


def test_window_stops_growing_at_the_limit(tmp_path, monkeypatch):
    import ai_cli.context as ctx

    monkeypatch.setattr(ctx, "TAIL_BYTES", 1024)
    monkeypatch.setattr(ctx, "MAX_TAIL_BYTES", 8192)
    text = _session(_block("too-far-back", "out\n", 0)) + "noise " * 100_000
    path = _write_session(tmp_path, monkeypatch, text)

    read = ctx.read_session_text(path)
    assert len(read) <= 8192
    with pytest.raises(ctx.NoSessionError, match="flooded"):
        get_blocks(1, path=path)


def test_sparse_recording_after_trimming_still_parses(tmp_path, monkeypatch):
    """The fish integration punches a hole into the front of a runaway recording;
    the hole reads back as NUL bytes and must not break parsing."""
    text = _session(_block("after-trim", "ok\n", 0))
    path = _write_session(tmp_path, monkeypatch, text, prefix=b"\0" * 50_000)

    assert [b.cmd for b in get_blocks(1, path=path)] == ["after-trim"]


def test_no_commands_in_a_small_recording_mentions_install(tmp_path, monkeypatch):
    import ai_cli.context as ctx

    path = _write_session(tmp_path, monkeypatch, "just some output, no markers")
    with pytest.raises(ctx.NoSessionError, match="ai install"):
        get_blocks(1, path=path)


def test_strip_ansi_removes_colors_and_osc():
    raw = "\x1b[31mred\x1b[0m\x1b]0;title\x07 text\r\nline\r"
    assert strip_ansi(raw) == "red text\nline"
