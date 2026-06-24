# ai-cli — project notes for Claude

CLI (`ai`) for OpenAI-API-compatible models. Python + uv. Two features:
1. `ai <question>` — ask anything; streams answer, offers to run suggested command.
2. `ai -N <instruction>` — explain the N-th last command + its output (Feature 2).

## Layout
- `src/ai_cli/cli.py` — entry point / dispatch (`-N` detection, subcommands).
- `src/ai_cli/config.py` — config precedence: CLI > env > TOML > default.
- `src/ai_cli/client.py` — OpenAI SDK wrapper, streaming.
- `src/ai_cli/ask.py` — Feature 1 + the `explain` flow (Feature 2 rendering).
- `src/ai_cli/context.py` — parses the recorded session typescript into command blocks.
- `src/ai_cli/shell.py` — shell/OS detection (fed into prompts).
- `src/ai_cli/run.py` — extract + confirm + run a suggested command.
- `src/ai_cli/integration.py` — `ai install` / `ai init`.
- `src/ai_cli/data/ai-cli.fish` — fish integration (single source of truth, shipped as package data).

## Feature 2 mechanism
Fish records the session with `script(1)`; `fish_preexec`/`fish_postexec` emit invisible
OSC markers: `ESC]1337;AICMD=<base64(cmd)>BEL ESC]133;C BEL` … `ESC]133;D;<exit>BEL`.
`context.py` parses completed blocks (those reaching a `D` marker); the in-progress `ai`
command has no `D` yet so it is excluded automatically.

## Conventions (user-mandated)
- Plans live in `plans/` named `YYYY-MM-DD_NNN_Short_Description.md` (date, 3-digit counter).
- Maintain `CHANGELOG.md` (Keep a Changelog style) on every change.

## Dev
- `uv sync` then `uv run pytest -q`.
- `uv run ai --help` / `ai config`.
