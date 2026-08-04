# ai

A small command-line tool for talking to OpenAI-API-compatible models, with two
features built for the terminal:

1. **Ask anything** — especially shell questions:

   ```
   ai how to list all files in the current folder sorted by size
   ```

   The answer is streamed as Markdown. If it suggests a command, you're asked
   whether to run it (never automatically).

   `ai` **starts an interactive chat by default** (see 3.), with your question as
   the first turn. Use `-p`/`--print` for a single answer that just prints and exits:

   ```
   ai -p how to list all files by size
   ```

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

   With `-p`, `-N` is the one-shot explanation:

   ```
   ai -p -1 explain
   ```

3. **Interactive chat** — the **default** mode, so plain `ai` opens a multi-turn chat:

   ```
   ai                        # plain chat
   ai wie geht das?          # chat, seeded with the question
   ai -3                     # chat seeded with the last 3 commands as context
   ai -1 "why?"              # context + an opening question
   ```

   Quit with **^D** or `exit` / `quit` / `bye` / `q`. When the assistant suggests a
   command you're asked to run it (y/N); its output is **fed back into the chat** so
   the assistant can react to the real result. Commands run on the real terminal, so
   `sudo` can prompt for a password (hidden). Line editing, history and the
   completion popup come from `prompt_toolkit`.

   `-i`/`--interactive` still works but is a no-op now that chat is the default.
   Without a usable terminal (output redirected, non-interactive script) `ai` falls
   back to printing a single answer automatically.

### Slash commands

Inside the chat, input starting with `/` is a command. Typing `/` opens a
completion popup listing every command with a short description; **Tab** completes.

| command           | description                                          |
|-------------------|------------------------------------------------------|
| `/clear`          | Clear the conversation history and the screen        |
| `/context [-N]`   | Load the last N commands + output as context         |
| `/model [name]`   | Show or switch the model for this session            |
| `/config`         | Show the effective configuration                     |
| `/help`           | List the available commands                          |
| `/exit`           | End the chat                                         |

### Referencing files with `@`

`@path` pulls a file or directory into the question. Typing `@` completes paths in
the popup (directories get a `/` so the next segment completes immediately):

```
you › was macht @src/ai_cli/session.py?
attached: @src/ai_cli/session.py (1.4 KiB)

you › vergleiche @altes.py mit @neues.py
you › was liegt in @src/ai_cli/ ?
```

The file's content (or the directory listing) is attached to that message, and a
status line states exactly what was sent. Works in the chat and with `-p`:

```
ai -p "erklär mir @src/ai_cli/cli.py"
```

Details: `@` only counts at the start of a token, so `daniel@dvs.ag` stays an email
address. `~` is expanded, `@"my file.txt"` covers spaces, and trailing sentence
punctuation (`@datei.py?`) is not treated as part of the path. Files are truncated
at 100 KiB, directory listings at 200 entries, and at most 10 references per
message are loaded; binary files and unknown paths are reported instead of sent.

`/clear` drops the dialogue only — context loaded via `-N`, a pipe or `/context`
stays, since it is part of the system prompt. Input starting with `/` that is not a
known command (e.g. `/tmp/foo — what is this?`) is sent to the model as usual.

**Piping:** anything piped into `ai` is added as input/context, so it composes with
other tools:

```
cat error.log | ai "why does this fail?"
curl -s https://en.wikipedia.org/api/rest_v1/page/summary/Albert_Einstein \
  | jq -r .extract | ai "übersetze das auf deutsch"
```

Piped input works with `-N` and in the chat too (the chat reconnects to `/dev/tty`
for your input). With `-p`, when stdin is piped, the run-it prompt is skipped
(there's no interactive input to answer it).

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

**Recording size.** Screen redraws are not recorded, and a recording never exceeds
**10 MiB**. `script` writes the raw stream into a FIFO, and a small filter process
writes the typescript from it:

```
fish └── script ──► session.fifo ──► ai _filter ──► session.typescript
```

The filter drops terminal control sequences — the constant redraws of editors and
TUIs, which used to inflate recordings to tens of GB — keeps the plain text and the
command markers, and rotates the file at 10 MiB (keeping the last 5 MiB). Override
with `AI_CLI_MAX_BYTES` / `AI_CLI_KEEP_BYTES`. If the filter cannot start, the shell
falls back to writing the typescript directly, where a per-command guard frees the
front of the file (`fallocate --punch-hole`) above the same limit. Independently of
all that, **every `ai` invocation** caps any recording that is over the limit — which
also covers shells that were started before the filter existed. Recordings with
no live writer are deleted above 10 MiB or after 14 days, and `ai -N` only ever
reads the tail of a recording, never the whole file.

## Commands

| command                 | description                                  |
|-------------------------|----------------------------------------------|
| `ai`                    | Interactive chat (default mode)              |
| `ai <question...>`      | Chat, seeded with the question               |
| `ai -N [text]`          | Chat with the last N commands as context     |
| `<cmd> \| ai [q...]`     | Pipe input as context for the question       |
| `ai -p <question...>`   | Print one answer and exit (Feature 1)        |
| `ai -p -N [text]`       | Print an explanation of the last N commands (Feature 2) |
| `ai install [fish]`     | Install shell integration                    |
| `ai init [fish]`        | Print integration snippet                    |
| `ai config`             | Show effective configuration                 |
| `ai version`            | Show the version (also `-V` / `--version`)   |
| `-p`, `--print`         | Print a single answer instead of starting a chat |
| `-i`, `--interactive`   | No-op (chat is the default); kept for compatibility |
| `--model <name>`        | Override the model for one call              |
| `--debug`               | With `-p -N`: print the command + output used as context, before the answer |

## Platform

Primarily Linux. macOS works (BSD `script` syntax is handled). Windows is best
effort — Feature 1 works; the recording-based Feature 2 needs a POSIX shell.
