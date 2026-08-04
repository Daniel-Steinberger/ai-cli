"""The filtering recording sink: sequence filtering, the ring buffer, and the pump."""

import base64
import os
import time
import threading

from ai_cli import recorder
from ai_cli.context import parse_blocks

MARKER_CMD = b"\x1b]1337;AICMD=" + base64.b64encode(b"ls -l") + b"\x07"
MARKER_OUT = b"\x1b]1337;AIOUT\x07"
MARKER_END = b"\x1b]1337;AIEND=0\x07"


def test_control_sequences_are_dropped():
    redraw = b"".join(f"\x1b[{row};185H\x1b[0;39;49m ".encode() for row in range(200))
    out, pending = recorder.filter_bytes(b"before" + redraw + b"after")
    assert out == b"before" + b" " * 200 + b"after"
    assert pending == b""


def test_our_markers_survive():
    data = b"\x1b[32m" + MARKER_CMD + MARKER_OUT + b"total 0\n" + MARKER_END + b"\x1b[0m"
    out, pending = recorder.filter_bytes(data)
    assert out == MARKER_CMD + MARKER_OUT + b"total 0\n" + MARKER_END
    assert pending == b""
    # And the result is still parseable as a command block.
    blocks = parse_blocks(out.decode())
    assert [(b.cmd, b.output, b.exit_code) for b in blocks] == [("ls -l", "total 0", 0)]


def test_other_osc_sequences_are_dropped():
    # Window title (OSC 0) and fish's own OSC 133 prompt markers are noise.
    data = b"\x1b]0;~/src/ai-cli\x07text\x1b]133;C\x07more"
    out, _ = recorder.filter_bytes(data)
    assert out == b"textmore"


def test_sequence_split_across_chunks_is_held_back():
    first, second = MARKER_CMD[:10], MARKER_CMD[10:]
    out, pending = recorder.filter_bytes(b"a" + first)
    assert out == b"a"
    assert pending == first
    out2, pending2 = recorder.filter_bytes(pending + second + b"b")
    assert out2 == MARKER_CMD + b"b"
    assert pending2 == b""


def test_two_byte_escapes_are_dropped_without_stalling():
    """The bug that silently stopped recording: fish emits ESC = / ESC > around the
    prompt. They matched no sequence, so everything after them was held back as a
    "possibly incomplete" sequence and the typescript stopped growing."""
    out, pending = recorder.filter_bytes(b"\x1b=eins\n\x1b>zwei\n")
    assert out == b"eins\nzwei\n"
    assert pending == b""


def test_charset_designation_and_string_sequences_are_dropped():
    out, pending = recorder.filter_bytes(b"a\x1b(Bb\x1bP1;2xyz\x1b\\c")
    assert out == b"abc"
    assert pending == b""


def test_stray_escape_mid_chunk_does_not_hold_back_the_rest():
    data = b"\x1b\x00" + b"x" * 4096  # ESC + NUL is not a sequence at all
    out, pending = recorder.filter_bytes(data)
    assert pending == b""
    assert out == b"\x00" + b"x" * 4096


def test_incomplete_osc_is_not_mistaken_for_a_two_byte_escape():
    # ESC ] must never match the "other escapes" branch, or a marker split across
    # reads would lose its head and leak base64 into the recorded text.
    out, pending = recorder.filter_bytes(b"x\x1b]1337;AIC")
    assert out == b"x"
    assert pending == b"\x1b]1337;AIC"


def test_ring_writer_caps_the_file(tmp_path):
    path = tmp_path / "s.typescript"
    writer = recorder.RingWriter(str(path), max_bytes=8192, keep_bytes=2048)
    for i in range(2000):
        writer.write(f"line {i}\n".encode())
    writer.close()

    size = path.stat().st_size
    assert size <= 8192
    text = path.read_text()
    assert "line 1999" in text  # the newest output is kept …
    assert "line 0" not in text  # … the oldest is dropped
    assert text.startswith("line ")  # cut at a line boundary


def test_ring_writer_keeps_recent_command_blocks(tmp_path):
    """After rotation `ai -N` must still find the most recent commands."""
    path = tmp_path / "s.typescript"
    writer = recorder.RingWriter(str(path), max_bytes=16384, keep_bytes=4096)
    for i in range(300):
        cmd = base64.b64encode(f"cmd{i}".encode())
        writer.write(b"\x1b]1337;AICMD=" + cmd + b"\x07" + MARKER_OUT
                     + f"output {i}\n".encode() + MARKER_END)
    writer.close()

    blocks = parse_blocks(path.read_text())
    assert blocks, "rotation must not destroy every block"
    assert blocks[-1].cmd == "cmd299"
    assert blocks[-1].output == "output 299"


def test_cap_recordings_punches_oversized_files(tmp_path):
    """The safety net for sessions without a cap of their own: free the front of the
    file, keep the tail that `ai -N` reads, leave the writer's offset alone."""
    import shutil

    if not shutil.which("fallocate"):
        return  # nothing to test without fallocate
    big = tmp_path / "big.typescript"
    big.write_bytes(b"x" * 300_000 + b"TAIL-MARKER")
    small = tmp_path / "small.typescript"
    small.write_bytes(b"y" * 1000)

    freed = recorder.cap_recordings(tmp_path, max_bytes=65536, keep_bytes=16384)

    assert freed > 0
    assert big.stat().st_size == 300_011  # apparent size unchanged (offset intact)
    assert big.stat().st_blocks * 512 <= 65536  # but the blocks are gone
    assert big.read_bytes().endswith(b"TAIL-MARKER")  # tail survives
    assert small.read_bytes() == b"y" * 1000  # untouched


def test_cap_recordings_is_quiet_without_a_directory(tmp_path):
    assert recorder.cap_recordings(tmp_path / "nope") == 0


def _pump_through_pipe(payload: bytes, tmp_path, **kwargs):
    """Run pump() against a pipe (a FIFO behaves the same for our purposes)."""
    read_fd, write_fd = os.pipe()
    out = tmp_path / "s.typescript"
    writer = recorder.RingWriter(str(out), **kwargs)

    def feed():
        os.write(write_fd, payload)
        os.close(write_fd)

    thread = threading.Thread(target=feed)
    thread.start()
    recorder.pump(read_fd, writer, startup_timeout=5.0, stop_on_eof=True)
    thread.join()
    writer.close()
    os.close(read_fd)
    return out.read_bytes()


def test_pump_filters_and_writes(tmp_path):
    payload = (b"\x1b[2J\x1b[H" + MARKER_CMD + MARKER_OUT
               + b"total 0\n" + MARKER_END + b"\x1b[0m")
    written = _pump_through_pipe(payload, tmp_path)
    assert written == MARKER_CMD + MARKER_OUT + b"total 0\n" + MARKER_END
    assert [b.cmd for b in parse_blocks(written.decode())] == ["ls -l"]


def test_pump_survives_a_redraw_flood_within_the_limit(tmp_path):
    flood = b"".join(f"\x1b[{r};80H\x1b[0mx".encode() for r in range(60)) * 2000
    payload = flood + MARKER_CMD + MARKER_OUT + b"done\n" + MARKER_END
    written = _pump_through_pipe(payload, tmp_path, max_bytes=65536, keep_bytes=16384)
    assert len(written) <= 65536
    assert [b.cmd for b in parse_blocks(written.decode())] == ["ls -l"]


def test_pump_keeps_reading_after_eof_while_the_writer_lives(tmp_path):
    """The bug that froze the shell: a gap in the stream (no data right now, or one
    writer closing) must not end the filter. script(1) would then be writing into a
    FIFO with no reader, where it busy-loops and the terminal becomes unusable."""
    fifo = tmp_path / "s.fifo"
    os.mkfifo(fifo)
    out = tmp_path / "s.typescript"
    writer = recorder.RingWriter(str(out))
    read_fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)

    done = threading.Event()

    def run():
        # stop_on_eof=False: production behaviour.
        recorder.pump(read_fd, writer, startup_timeout=10.0)
        done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    # First writer: sends data, then closes -> the fd reports EOF.
    with open(fifo, "wb") as fh:
        fh.write(b"first\n")
    time.sleep(0.3)
    assert not done.is_set(), "pump must not exit on EOF while the parent is alive"

    # A later writer must still be picked up.
    with open(fifo, "wb") as fh:
        fh.write(MARKER_CMD + MARKER_OUT + b"second\n" + MARKER_END)
    time.sleep(0.3)

    os.close(read_fd)  # unblock the thread for the test to finish
    thread.join(timeout=5)
    writer.close()

    written = out.read_bytes()
    assert b"first" in written and b"second" in written
    assert [b.cmd for b in parse_blocks(written.decode())] == ["ls -l"]


def test_pump_gives_up_once_the_write_end_stays_gone(tmp_path):
    """Backstop for a recycled watch pid: if nothing holds the write end for longer
    than the grace period, exit even though the watched pid still looks alive."""
    fifo = tmp_path / "s.fifo"
    os.mkfifo(fifo)
    writer = recorder.RingWriter(str(tmp_path / "s.typescript"))
    read_fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        with open(fifo, "wb") as fh:  # one writer, then gone for good
            fh.write(b"data\n")
        started = time.monotonic()
        # watch_pid=1 (init) never dies, so only the grace period can end this.
        recorder.pump(read_fd, writer, watch_pid=1, eof_grace=0.5)
        assert time.monotonic() - started < 5
    finally:
        os.close(read_fd)
        writer.close()


def test_dying_filter_hangs_up_its_writer(tmp_path):
    """If the filter goes away, script(1) would be left writing into a reader-less
    FIFO — where it busy-loops and the terminal is unusable. So on the way out the
    filter sends SIGHUP to its parent (script), ending the session instead."""
    import signal as sig
    import subprocess
    import sys

    fifo = tmp_path / "s.fifo"
    os.mkfifo(fifo)
    out = tmp_path / "s.typescript"

    got_hup = threading.Event()
    previous = sig.signal(sig.SIGHUP, lambda *_: got_hup.set())
    try:
        child = subprocess.Popen(
            [sys.executable, "-c",
             "from ai_cli.recorder import main; main(['%s', '%s'])" % (fifo, out)],
        )
        for _ in range(100):  # wait for the ready flag
            if (tmp_path / "s.fifo.ready").exists():
                break
            time.sleep(0.05)
        # Feed it something so it knows it is really the sink.
        with open(fifo, "wb") as fh:
            fh.write(b"data\n")
        time.sleep(0.3)
        child.terminate()
        child.wait(timeout=5)
        for _ in range(40):
            if got_hup.is_set():
                break
            time.sleep(0.05)
        assert got_hup.is_set(), "the filter must hang up its writer when it exits"
    finally:
        sig.signal(sig.SIGHUP, previous)


def test_pump_write_failure_does_not_stop_reading(tmp_path):
    """A failing write must never stall the reader — script blocks on a full FIFO
    and that would freeze the user's shell."""
    read_fd, write_fd = os.pipe()

    class Failing(recorder.RingWriter):
        def __init__(self):
            self.calls = 0

        def write(self, data):
            self.calls += 1
            raise OSError("disk on fire")

        def close(self):
            pass

    writer = Failing()

    def feed():
        for _ in range(50):
            os.write(write_fd, b"some output\n")
        os.close(write_fd)

    thread = threading.Thread(target=feed)
    thread.start()
    recorder.pump(read_fd, writer, startup_timeout=5.0, stop_on_eof=True)  # must return, not hang
    thread.join()
    os.close(read_fd)
    assert writer.calls >= 1
