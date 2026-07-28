# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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

### Added
- **Piped stdin as context:** when input is piped into `ai` (stdin is not a TTY),
  it is read and attached to the question/instruction — e.g.
  `cat err.log | ai "why?"` or `… | jq -r .extract | ai "übersetze das"`. Works with
  Feature 1, `-N` and `-i` (chat reconnects to `/dev/tty` for input). The run-it
  prompt is skipped when stdin is piped (no interactive answer possible).
- **Interactive chat mode** (`ai -i`): multi-turn conversation with readline line
  editing/history, exit via ^D or `exit`/`quit`/`bye`/`q`. Optional leading `-N`
  and/or text seed the chat with recent-command context. Suggested commands can be
  run (y/N) and their output is **fed back into the conversation**; commands run on
  the real terminal via a PTY, so `sudo` can prompt for a password (hidden, and not
  captured into the chat). No new dependencies (`readline`/`pty` are stdlib).

### Changed
- `-N` now uses the **last N commands** as context (oldest first), not just the
  N-th last single command. `-1` is the previous command, `-3` the last three.

### Added
- `--debug` flag: when used with `-N`, prints the command(s), exit code(s) and
  output(s) used as context (before the model is contacted).

### Docs
- Clarify how to update a locally-installed tool (`uv tool install . --reinstall`);
  `uv tool upgrade` only works for git/index installs.

### Fixed
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

### Added
- `config.toml.example` at the repo root, kept in sync with `config.py`.

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
