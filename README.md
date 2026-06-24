# ai

A small command-line tool for talking to OpenAI-API-compatible models, with two
features built for the terminal:

1. **Ask anything** — especially shell questions:

   ```
   ai how to list all files in the current folder sorted by size
   ```

   The answer is streamed as Markdown. If it suggests a command, you're asked
   whether to run it (never automatically).

2. **Explain the previous command** — read a recent command *and its output* and
   interpret a follow-up instruction in that context:

   ```
   dst@pc ~/s/ai-cli> ls -l
   total 0
   dst@pc ~/s/ai-cli> ai -1 explain
   ```

   `-N` goes back N commands (`-1` is the previous one). The instruction after it
   (`explain`, `"why did this fail?"`, …) is interpreted against that command,
   its output, and its exit code.

The tool is **shell-aware** (fish/zsh/bash): the detected shell and OS are passed
to the model so answers and suggested commands match your environment.

## Install

```sh
uv sync
```

## Configure

API endpoint, key and model are read from environment variables, with an optional
TOML config file. Precedence: CLI flag > env var > config file > default.

| setting   | env var            | config key  | default                        |
|-----------|--------------------|-------------|--------------------------------|
| API key   | `OPENAI_API_KEY`   | `api_key`   | —                              |
| Base URL  | `OPENAI_BASE_URL`  | `base_url`  | `https://api.openai.com/v1`    |
| Model     | `AI_MODEL`         | `model`     | `gpt-4o-mini`                  |

Config file lives at `~/.config/ai-cli/config.toml`:

```toml
base_url = "https://api.openai.com/v1"
model    = "gpt-4o-mini"
# api_key = "sk-..."   # optional; prefer the OPENAI_API_KEY env var
```

Run `ai config` to see the effective values and where each came from.

## Enabling `ai -N` (shell integration)

Reading a previous command's **output** is impossible after the fact unless the
session is recorded. The integration records your interactive shell with
`script(1)` and marks command boundaries with invisible terminal control
sequences (OSC 133). Currently supported: **fish**.

```sh
ai install        # writes ~/.config/fish/conf.d/ai-cli.fish
exec fish         # start a recorded session
```

Then `ai -1 explain` works. To try it without installing:

```sh
ai init fish | source
```

## Commands

| command                 | description                                  |
|-------------------------|----------------------------------------------|
| `ai <question...>`      | Ask anything (Feature 1)                     |
| `ai -N <instruction>`   | Explain the N-th last command (Feature 2)    |
| `ai install [fish]`     | Install shell integration                    |
| `ai init [fish]`        | Print integration snippet                    |
| `ai config`             | Show effective configuration                 |
| `--model <name>`        | Override the model for one call              |

## Platform

Primarily Linux. macOS works (BSD `script` syntax is handled). Windows is best
effort — Feature 1 works; the recording-based Feature 2 needs a POSIX shell.
