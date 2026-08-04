# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- **Redraws are no longer recorded at all, and a recording never exceeds 10 MiB.**
  `script(1)` now writes into a FIFO and a new filter process (`ai _filter`,
  module `recorder.py`) writes the typescript: it drops CSI sequences (cursor
  moves, colours — i.e. the screen redraws of editors and TUIs) and foreign OSC
  sequences, keeps the plain text and our own OSC 1337 markers, and rotates the
  file at 10 MiB (keeping the last 5 MiB, cut at a line boundary). Overridable via
  `AI_CLI_MAX_BYTES` / `AI_CLI_KEEP_BYTES`. Measured: 8000 redraw sequences that
  previously bloated the file now leave a 9 KB typescript with zero CSI sequences,
  and `ai -N` still finds the commands. The filter must never stall (a full FIFO
  blocks script and would freeze the shell), so write errors drop data instead, and
  it opens the FIFO non-blocking and publishes a `.ready` flag — if it does not
  appear, the shell falls back to writing the typescript directly. Should the
  filter die anyway, it hangs up `script` on the way out rather than leave it
  busy-looping on a reader-less FIFO (not possible under `SIGKILL`/OOM, where the
  next shell start reaps it). Set `AI_CLI_FILTER_DEBUG=1` to have the filter log
  what it reads. **Re-run `ai install` and restart your shell.**
- **Every `ai` invocation now caps oversized recordings** (`recorder.cap_recordings`,
  ~2 ms when there is nothing to do). The per-session guards only protect sessions
  that were started *with* them: a long-running shell from before the filter existed
  has no cap of its own, and a redraw-heavy TUI in such a session fills the disk at
  gigabytes per hour — measured 7 GB/h, 440 GiB in five days. Any recording above
  the limit gets the front punched out, keeping the tail `ai -N` reads and leaving
  the writer's offset untouched, so recording continues unaffected.
- Pruning now removes leftover recordings with no live writer above **10 MiB**
  (was 500 MiB) — that is the size a filtered recording is capped at, so anything
  larger is a leftover from before the cap existed.

### Fixed
- **Ctrl-D did not end the shell** (and the terminal window would not close) with
  the filtered recording in place. The filter was started from the shell, so it was
  a child of `script(1)` — and script waits for its children before exiting. It also
  inherited the pty slave on stdin, and script only sees EOF on the master once
  nobody holds the slave. The filter now drops all inherited terminal descriptors
  (`os.setsid()` plus `/dev/null` on stdin/stdout/stderr), double-forks so it is
  re-parented to init, and watches the shell's pid — passed as a third argument —
  to know when script is gone. As a backstop against that pid being recycled, it
  also exits once the write end of the FIFO has stayed closed for 10 seconds.
- **`MemoryError` in `ai -N`.** `read_session_text()` loaded the whole typescript
  into memory; a session that ran a full-screen program (editor, TUI, `claude`)
  records every screen redraw and had grown to **84.5 GiB**, so the read died with
  a traceback. Only the *end* of the recording is read now: an 8 MiB window at the
  tail, doubled until it contains a finished command (`AIEND`), capped at 64 MiB.
  If no command is in that window, the message says so instead of raising
  (0.33 s against the real 84.5 GiB file). Every caller now catches
  `context.CONTEXT_ERRORS` (`NoSessionError`/`ValueError`/`OSError`/`MemoryError`),
  so a read failure can no longer surface as a traceback.
- **Recordings no longer grow without bound.** The existing pruning only ever
  touched typescripts with *no live writer*, so a healthy recorder in front of a
  redraw-heavy TUI could fill the disk. A new `fish_postexec` guard punches a hole
  into the front of its own session (`fallocate --punch-hole`) once its allocated
  size passes 512 MiB, keeping the last 32 MiB — the part `ai -N` reads. A plain
  truncate would free nothing, because `script` writes sequentially at a rising
  offset rather than in append mode. Limits are overridable via `AI_CLI_MAX_BYTES`
  / `AI_CLI_KEEP_BYTES`; the guard is skipped where `fallocate` is unavailable.
  **Re-run `ai install` and restart your shell** to pick this up.

## [0.2.0] - 2026-07-29

### Changed
- **Interactive chat is now the default** (like `claude`). Plain `ai` opens the
  chat; `ai <frage>` opens it with the question as the first turn; `ai -N [text]`
  opens it with the last N commands as context. The new **`-p`/`--print`** flag
  restores the old one-shot behaviour (`ai -p <frage>`, `ai -p -N [text]`).
  `-i`/`--interactive` is kept as a no-op alias. Without a usable terminal
  (redirected output, non-interactive script) `ai` falls back to print mode
  automatically instead of failing.
- `-N` now uses the **last N commands** as context (oldest first), not just the
  N-th last single command. `-1` is the previous command, `-3` the last three.

### Added
- **Version output:** `ai --version` / `-V` / `ai version`. `ai_cli.__version__` is
  read from the installed package metadata, so `pyproject.toml` stays the only
  place the version is defined. Previously `ai --version` was sent to the model as
  a question.
- **`@path` references.** `@datei.py` / `@verzeichnis` in a question attaches that
  file's content (or the directory listing) as context — in the chat and with `-p`
  / `-p -N`. Paths are completed in the popup (`file`/`directory` as meta text,
  directories get a `/` so the next segment completes right away). `@` only counts
  at the start of a token, so `daniel@dvs.ag` stays an email address; quoting
  (`@"my file.txt"`) covers spaces, `~` is expanded, and trailing sentence
  punctuation (`@datei.py?`) is not part of the path. Limits: 100 KiB per file
  (truncated with a note), 200 directory entries, 10 references per message;
  binary files are reported, not inlined. A status line shows exactly what was
  attached — or why it was not (`not found`, `binary`, …).
- **Slash commands in the chat** with a live **autocompletion popup**: typing `/`
  opens a menu listing every command with a short description (omnibar style),
  Tab completes. Commands: `/clear` (drop the conversation and clear the screen;
  loaded context is kept, as it lives in the system prompt), `/context [-N]`
  (load the last N commands + output into the running session), `/model [name]`
  (show or switch the model), `/config`, `/help`, `/exit`. Input starting with `/`
  that is not a known command (e.g. `/tmp/foo — was ist das?`) still goes to the
  model.
- New modules `session.py` (`ChatSession`: system prompt, messages, context) and
  `commands.py` (command registry + dispatch + completions). New dependency
  `prompt_toolkit` (drives the chat prompt and the popup); stdlib `readline`
  remains the fallback when it is unavailable, minus the popup.
- **Piped stdin as context:** when input is piped into `ai` (stdin is not a TTY),
  it is read and attached to the question/instruction — e.g.
  `cat err.log | ai "why?"` or `… | jq -r .extract | ai "übersetze das"`. Works with
  Feature 1, `-N` and the chat (which reconnects to `/dev/tty` for input). With
  `-p` the run-it prompt is skipped when stdin is piped (no interactive answer
  possible).
- **Interactive chat mode**: multi-turn conversation with line editing/history,
  exit via ^D or `exit`/`quit`/`bye`/`q`. Optional leading `-N` and/or text seed
  the chat with recent-command context. Suggested commands can be run (y/N) and
  their output is **fed back into the conversation**; commands run on the real
  terminal via a PTY, so `sudo` can prompt for a password (hidden, and not
  captured into the chat).
- `--debug` flag: when used with `-N`, prints the command(s), exit code(s) and
  output(s) used as context (before the model is contacted).
- `config.toml.example` at the repo root, kept in sync with `config.py`.

### Fixed
- **Runaway session recordings.** The fish integration now cleans up on every
  real terminal launch: it *reaps* orphaned `script(1)` recorders (parent
  reparented to pid 1 / `systemd` — the busy-loop case that `setpriv --pdeathsig`
  cannot catch when the terminal's pty dies but the parent process survives) and
  deletes their runaway typescripts, and it *prunes* leftover recordings with no
  live writer that exceed 500 MiB or are older than 14 days. Files a live
  recorder still holds open are protected. Previously such orphans could grow to
  hundreds of GB and there was no rotation of old sessions.
- **Interactive chat backspace/cursor math** (`ai -i`): the `you ›` prompt was
  rendered via Rich's `console.input`, which prints the prompt and then calls
  `input("")`, leaving readline blind to the prompt width. Cursor calculations
  (backspace, line wrapping) were off by the prompt width. The prompt is now
  passed to the builtin `input()` with its escape sequences wrapped in
  `\001..\002` so readline counts the on-screen width correctly.
- Bracketed placeholders (`[text...]`, `[fish]`, `/model [name]`) no longer vanish
  from `ai --help` and `/help`: those strings were parsed as Rich markup tags.
- Recorder no longer lingers/busy-loops as an orphan after a terminal restart.
  The fish integration `exec`s the interactive shell inside `script(1)`. When the
  owning terminal process (e.g. `ptyxis-agent`) died *without* closing the pty —
  a terminal/compositor restart or crash — `script` was reparented to the user's
  init manager and never exited, busy-looping on the now-unreadable terminal
  (steady system load, ~100% of one core each). On Linux the recorder is now
  launched via `setpriv --pdeathsig HUP script …`, so it is signalled to exit the
  moment its parent terminal goes away. A clean `Ctrl-D` is unaffected (the parent
  stays alive; only the individual shell exits). Falls back to bare `script` if
  `setpriv` is unavailable. **Re-run `ai install` and restart your shell** to pick
  this up in existing setups.
- Options (`--debug`, `--model`) are now recognised anywhere in the arguments,
  including after the `-N` offset (e.g. `ai -3 --debug explain`). Previously only
  leading options were parsed, so `--debug` after `-N` leaked into the instruction.
- Use unique OSC 1337 markers (`AICMD`/`AIOUT`/`AIEND`) instead of OSC 133.
  fish 4.x emits its own OSC 133 prompt markers, which collided with ours and
  corrupted block parsing (duplicate/orphaned markers, wrong command selected).
  **Re-run `ai install` and restart your shell** after upgrading.
- fish integration now records with `script -f` (flush after each write) so
  `ai -N` immediately sees the most recent command instead of lagging behind
  `script`'s block buffer.

### Docs
- Clarify how to update a locally-installed tool (`uv tool install . --reinstall`);
  `uv tool upgrade` only works for git/index installs.

## [0.1.0] - 2026-06-24

### Added
- Initial project scaffold (Python + uv, `ai` console script).
- **Feature 1 — ask anything:** `ai <question>` streams a Markdown answer from an
  OpenAI-compatible model and offers to run a suggested command (y/N, never
  automatic).
- **Feature 2 — explain previous command:** `ai -N <instruction>` reads the N-th
  last command, its output and exit code from a recorded session and interprets
  the instruction in that context.
- **fish shell integration** (`ai install` / `ai init fish`): records the session
  with `script(1)` and marks command boundaries with OSC markers; parsed by
  `ai_cli.context`.
- **Shell awareness:** detected shell (fish/zsh/bash) + version + OS are passed to
  the model so answers and commands match the environment.
- **Configuration** via env vars (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `AI_MODEL`)
  and `~/.config/ai-cli/config.toml`; `ai config` shows effective values + source.
- Tests for the typescript parser, config precedence and CLI argument dispatch.
