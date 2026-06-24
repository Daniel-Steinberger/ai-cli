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

   `-N` uses the **last N commands** as context (`-1` is just the previous one,
   `-3` the last three). The instruction after it (`explain`, `"why did this
   fail?"`, …) is interpreted against those commands, their output, and exit codes.
   Add `--debug` to print exactly what was used as context.

3. **Interactive chat** — `ai -i` opens a multi-turn chat:

   ```
   ai -i                     # plain chat
   ai -i -3                  # chat seeded with the last 3 commands as context
   ai -i -1 "why?"           # context + an opening question
   ```

   Quit with **^D** or `exit` / `quit` / `bye` / `q`. When the assistant suggests a
   command you're asked to run it (y/N); its output is **fed back into the chat** so
   the assistant can react to the real result. Commands run on the real terminal, so
   `sudo` can prompt for a password (hidden). Line editing and history come from
   readline.

The tool is **shell-aware** (fish/zsh/bash): the detected shell and OS are passed
to the model so answers and suggested commands match your environment.

## Install

### As a global tool (recommended)

Install the `ai` command onto your `PATH` with uv — no `uv run` prefix needed
afterwards (this also matters for Feature 2, which calls `ai` from inside your
recorded shell):

```sh
# From a local checkout:
uv tool install .

# Or straight from the repository (once pushed):
uv tool install git+https://github.com/<you>/ai-cli
```

After installing, `ai`, `ai install`, `ai config`, etc. work directly.

**Updating after code changes:** a local `uv tool install .` is a frozen snapshot
— it does *not* pick up later edits to the checkout, and `uv tool upgrade` only
works for git/index installs. After pulling or editing the source, reinstall:

```sh
uv tool install . --reinstall      # local checkout: rebuild from current source
uv tool upgrade ai-cli             # only for git/index installs
```

During development you can skip the global install entirely and use `uv run ai …`
from the checkout (always runs current source).

Run it once without installing (ephemeral, from a checkout):

```sh
uvx --from . ai how to list files by size
```

### For development

```sh
uv sync
uv run ai --help
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
| `ai -N <instruction>`   | Explain the last N commands (Feature 2)      |
| `ai -i [-N] [text]`     | Interactive chat; optional `-N`/text seed context |
| `ai install [fish]`     | Install shell integration                    |
| `ai init [fish]`        | Print integration snippet                    |
| `ai config`             | Show effective configuration                 |
| `-i`, `--interactive`   | Start an interactive chat                    |
| `--model <name>`        | Override the model for one call              |
| `--debug`               | With `-N`: print the command + output used as context, before the answer |

## Platform

Primarily Linux. macOS works (BSD `script` syntax is handled). Windows is best
effort — Feature 1 works; the recording-based Feature 2 needs a POSIX shell.
