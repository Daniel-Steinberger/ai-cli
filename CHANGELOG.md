# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
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
