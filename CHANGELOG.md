# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `--debug` flag: when used with `-N`, prints the command, exit code and output
  that were used as context (before the model's answer).

### Fixed
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
