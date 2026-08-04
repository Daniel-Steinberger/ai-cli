"""Filtering sink for the session recording — `ai _filter <fifo> <typescript>`.

The fish integration no longer lets `script(1)` write the typescript directly.
Instead script writes the raw terminal stream into a FIFO and this process is the
reader: it throws away terminal control sequences — a full-screen program (editor,
TUI, `claude`) redraws the whole screen continuously, which is what used to inflate
recordings to tens of GB — keeps our own OSC 1337 markers and the plain text, and
appends that to the typescript, rotating it so the file never exceeds MAX_BYTES.

Two invariants matter here:

* **Reading must never stop.** script blocks once the FIFO buffer is full, which
  would freeze the user's interactive shell. Every write error is therefore
  swallowed: we drop data rather than stall.
* **Opening must never block.** The FIFO is opened O_NONBLOCK so this process is
  ready before script opens the write end (fish waits for the `.ready` file and
  falls back to writing the typescript directly if it does not appear).
"""

from __future__ import annotations

import os
import re
import select
import signal
import sys
import time

CHUNK = 1 << 16
MAX_BYTES = 10 * 1024 * 1024
KEEP_BYTES = 5 * 1024 * 1024

# An escape sequence split across two reads is held back until it completes; beyond
# this many bytes we assume it never will and drop the ESC (keeps memory bounded
# while still covering a long AICMD marker, whose payload is base64 of a command).
MAX_PENDING = 8192

# Wait this long for script to show up on the write end before giving up.
STARTUP_TIMEOUT = 30.0
# Once the write end is gone for this long we exit even if the watched pid still
# looks alive — guards against the pid having been recycled by an unrelated process.
EOF_GRACE = 10.0

_SEQ = re.compile(
    rb"\x1b\](?P<osc>[^\x07\x1b]*)(?:\x07|\x1b\\)"  # OSC … BEL / ST
    rb"|\x1b[P^_X][^\x1b\x07]*(?:\x1b\\|\x07)"  # DCS / PM / APC / SOS strings
    rb"|\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI (cursor moves, colours, redraws)
    rb"|\x1b[()*+#%][0-9A-Za-z@]"  # charset designation, e.g. ESC ( B
    # Anything else that is a two-byte escape, e.g. fish's keypad switches ESC =
    # and ESC >. This must stay LAST so the longer forms above win.
    rb"|\x1b[ -~]"
)

# An escape that could still become one of the above with more input: a bare ESC at
# the very end, an OSC without its terminator, a CSI without its final byte, or a
# charset designation missing its last byte. `\Z` pins it to the end of the chunk —
# an ESC in the middle that matches nothing is junk, not a truncated sequence.
_INCOMPLETE = re.compile(rb"\x1b(?:\][^\x07\x1b]*|\[[0-9;?]*[ -/]*|[()*+#%]|)\Z")
# Only our own markers survive; every other control sequence is noise for `ai -N`.
_KEEP_OSC = b"1337;AI"


def filter_bytes(data: bytes) -> tuple[bytes, bytes]:
    """Strip control sequences, keeping text and our OSC 1337 markers.

    Returns (filtered, pending) where `pending` is a trailing, still-incomplete
    escape sequence that the caller must prepend to the next chunk.
    """
    out = bytearray()
    pos = 0
    while True:
        esc = data.find(b"\x1b", pos)
        if esc < 0:
            out += data[pos:]
            return bytes(out), b""
        out += data[pos:esc]
        # Hold back only what can still grow into a sequence, and only near the end
        # of the chunk — otherwise a single stray ESC would stall the whole stream.
        if len(data) - esc < MAX_PENDING and _INCOMPLETE.match(data, esc):
            return bytes(out), data[esc:]
        match = _SEQ.match(data, esc)
        if match:
            osc = match.group("osc")
            if osc is not None and osc.startswith(_KEEP_OSC):
                out += match.group(0)
            pos = match.end()
            continue
        pos = esc + 1  # nothing we recognise: drop the ESC, keep the rest as text


class RingWriter:
    """Append-only writer that keeps the file below `max_bytes` by dropping the
    front (the oldest output) once it grows past the limit."""

    def __init__(self, path: str, max_bytes: int = MAX_BYTES, keep_bytes: int = KEEP_BYTES):
        self.max_bytes = max(max_bytes, 4096)
        self.keep_bytes = min(max(keep_bytes, 1024), self.max_bytes // 2)
        self.fh = open(path, "w+b", buffering=0)

    def write(self, data: bytes) -> None:
        if not data:
            return
        self.fh.seek(0, os.SEEK_END)
        self.fh.write(data)
        if self.fh.tell() > self.max_bytes:
            self._rotate()

    def _rotate(self) -> None:
        """Keep the last `keep_bytes`, cut at a line boundary so the retained part
        does not start in the middle of a line."""
        size = self.fh.seek(0, os.SEEK_END)
        self.fh.seek(size - self.keep_bytes)
        tail = self.fh.read(self.keep_bytes)
        newline = tail.find(b"\n")
        if 0 <= newline < 4096:
            tail = tail[newline + 1:]
        self.fh.seek(0)
        self.fh.write(tail)
        self.fh.truncate()

    def close(self) -> None:
        try:
            self.fh.close()
        except OSError:
            pass


def _detach_terminal() -> None:
    """Let go of every inherited terminal fd and leave the session.

    Critical: the filter is started from the shell and inherits the pty slave on
    stdin. script(1) exits when it reads EOF on the pty *master*, and that EOF only
    arrives once nobody holds the slave any more. A filter still holding it means
    Ctrl-D never ends the shell — script spins instead of exiting and the terminal
    window will not close.
    """
    try:
        devnull = os.open(os.devnull, os.O_RDWR)
    except OSError:
        return
    keep_stderr = bool(os.environ.get("AI_CLI_FILTER_DEBUG"))
    for target in (0, 1) if keep_stderr else (0, 1, 2):
        try:
            os.dup2(devnull, target)
        except OSError:
            pass
    if devnull > 2:
        try:
            os.close(devnull)
        except OSError:
            pass
    try:
        os.setsid()  # no controlling terminal at all
    except OSError:
        pass  # already a session leader


def _debug(message: str) -> None:
    """Diagnostics on stderr when AI_CLI_FILTER_DEBUG is set (the shell sends the
    filter's stderr to /dev/null, so this is opt-in only)."""
    if os.environ.get("AI_CLI_FILTER_DEBUG"):
        try:
            sys.stderr.write(f"[ai _filter] {message}\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass


def _daemonize() -> None:
    """Fork twice so we end up re-parented to init.

    We must not remain a child of script(1): script waits for its children before
    exiting, so a filter hanging off it means Ctrl-D never ends the shell and the
    terminal window stays open. Detached this way, script sees only its shell as a
    child and exits normally — we watch it by pid instead (see `_writer_gone`).
    """
    if os.fork() > 0:
        os._exit(0)
    try:
        os.setsid()
    except OSError:
        pass
    if os.fork() > 0:
        os._exit(0)


def _writer_gone(watch_pid: int | None, initial_ppid: int) -> bool:
    """Has the process feeding us disappeared?

    With an explicit pid (production: the shell pid, which becomes script after its
    exec) we probe that pid, because after `_daemonize` our own parent is init. The
    parent-based fallback is what the tests use.
    """
    if watch_pid:
        try:
            os.kill(watch_pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False
    ppid = os.getppid()
    return ppid != initial_ppid or ppid == 1


def pump(fd: int, writer: RingWriter, *, initial_ppid: int | None = None,
         startup_timeout: float = STARTUP_TIMEOUT, state: dict | None = None,
         stop_on_eof: bool = False, watch_pid: int | None = None,
         eof_grace: float = EOF_GRACE) -> bool:
    """Read the raw stream from `fd` until the writer closes it, filtering as we go.

    Returns True if any data was received, i.e. we really were script's sink. The
    same flag is mirrored into `state["fed"]` so a caller interrupted by a signal
    still knows whether it had been the sink.
    """
    ppid = os.getppid() if initial_ppid is None else initial_ppid
    pending = b""
    seen_data = False
    deadline = time.monotonic() + startup_timeout
    no_writer_since = None
    while True:
        try:
            ready, _, _ = select.select([fd], [], [], 0.5)
        except (OSError, ValueError):  # fd closed underneath us
            return seen_data
        if ready:
            try:
                chunk = os.read(fd, CHUNK)
            except BlockingIOError:
                chunk = None  # no data *right now* — emphatically not EOF
            except InterruptedError:
                continue
            except OSError:
                return seen_data
            if chunk == b"" and no_writer_since is None:
                # read() == 0 on an O_NONBLOCK FIFO means "no writer attached", as
                # opposed to BlockingIOError, which means "no data right now".
                no_writer_since = time.monotonic()
            if chunk:
                _debug(f"read {len(chunk)} bytes")
                seen_data = True
                no_writer_since = None
                if state is not None:
                    state["fed"] = True
                text, pending = filter_bytes(pending + chunk)
                try:
                    writer.write(text)
                except OSError:
                    pass  # never stop reading: a blocked FIFO would freeze the shell
                continue

        # No data. On a FIFO opened O_NONBLOCK, "no writer yet" and "writer closed"
        # both surface as EOF, so we do NOT end on EOF alone: as long as script(1)
        # is alive we keep reading. Quitting early would leave script writing into a
        # FIFO with no reader, where it busy-loops and the shell becomes unusable.
        if stop_on_eof and seen_data:
            return seen_data  # plain pipe: EOF is final (used by the tests)
        if _writer_gone(watch_pid, ppid):
            _debug("writer gone -> exit")
            return seen_data
        if (seen_data and no_writer_since is not None
                and time.monotonic() - no_writer_since > eof_grace):
            _debug("write end gone for good -> exit")
            return seen_data
        if not seen_data and time.monotonic() > deadline:
            return seen_data  # nobody ever showed up on the write end (shell took the fallback)
        time.sleep(0.05)  # do not spin: an EOF-ready FIFO selects readable forever


def cap_recordings(directory=None, max_bytes: int | None = None,
                   keep_bytes: int | None = None) -> int:
    """Punch the front out of any recording that exceeds the cap. Returns bytes freed.

    This runs on *every* `ai` invocation as a safety net independent of the shell
    integration: a session started before the filter existed (or one where the
    filter could not start) has no cap of its own, and a redraw-heavy TUI in such a
    session fills the disk at gigabytes per hour. Punching keeps the tail — the part
    `ai -N` reads — and leaves the writer's offset alone, so recording continues
    unaffected. Never raises: this must not disturb the actual command.
    """
    import shutil
    import subprocess

    from .config import log_dir

    max_bytes = max_bytes or _int_env("AI_CLI_MAX_BYTES", MAX_BYTES)
    keep_bytes = keep_bytes or _int_env("AI_CLI_KEEP_BYTES", KEEP_BYTES)
    keep_bytes = min(keep_bytes, max_bytes // 2)
    freed = 0
    try:
        directory = directory or log_dir()
        if not shutil.which("fallocate") or not directory.is_dir():
            return 0
        for path in directory.glob("*.typescript"):
            try:
                st = path.stat()
                if st.st_blocks * 512 <= max_bytes:
                    continue
                hole = st.st_size - keep_bytes
                if hole <= 0:
                    continue
                # fallocate --punch-hole: a plain truncate would free nothing here,
                # because script(1) writes sequentially at a rising offset.
                subprocess.run(["fallocate", "-p", "-o", "0", "-l", str(hole), str(path)],
                               check=True, capture_output=True, timeout=30)
                freed += st.st_blocks * 512 - path.stat().st_blocks * 512
                _debug(f"punched {path.name}")
            except (OSError, subprocess.SubprocessError):
                continue
    except (OSError, ValueError):
        return freed
    return freed


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def main(argv: list[str]) -> int:
    """`ai _filter <fifo> <typescript> [watch-pid]` — internal, started by the shell.

    `watch-pid` is the shell's pid, which becomes script(1) after its exec: we exit
    when it goes away. Passing it also enables detaching from the process tree.
    """
    if len(argv) < 2:
        return 2
    fifo, out_path = argv[0], argv[1]
    watch_pid = None
    if len(argv) > 2:
        try:
            watch_pid = int(argv[2])
        except ValueError:
            watch_pid = None
    ready = f"{fifo}.ready"
    _detach_terminal()
    if watch_pid:
        # Only in the real shell chain; without a pid to watch there is no chain to
        # detach from and the tests can drive main() directly.
        _daemonize()

    def stop(signum, frame):
        raise SystemExit(0)

    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)

    try:
        fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return 1
    writer = None
    ppid = os.getppid()
    state = {"fed": False}
    try:
        writer = RingWriter(
            out_path,
            max_bytes=_int_env("AI_CLI_MAX_BYTES", MAX_BYTES),
            keep_bytes=_int_env("AI_CLI_KEEP_BYTES", KEEP_BYTES),
        )
        # Signal readiness only once we can actually read and write.
        with open(ready, "wb"):
            pass
        pump(fd, writer, state=state, watch_pid=watch_pid)
    except (SystemExit, KeyboardInterrupt):
        pass
    except OSError:
        return 1
    finally:
        # If we were script's sink and it is still alive, hang it up on the way out.
        # A reader-less FIFO makes script busy-loop and the shell unusable, so ending
        # the session is the lesser evil. `fed` guards the fallback case, where the
        # shell gave up on us and script legitimately writes the typescript itself.
        if state["fed"] and not _writer_gone(watch_pid, ppid):
            try:
                os.kill(watch_pid or ppid, signal.SIGHUP)
            except OSError:
                pass
        if writer is not None:
            writer.close()
        try:
            os.close(fd)
        except OSError:
            pass
        for path in (fifo, ready):
            try:
                os.unlink(path)
            except OSError:
                pass
    return 0
