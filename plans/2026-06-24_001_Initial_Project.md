# Plan: `ai` — CLI für OpenAI-kompatible Modelle

## Context

Neues Greenfield-Projekt in `/home/dst/src/ai-cli` (aktuell leer, kein Git). Ziel ist ein
CLI-Tool `ai` (Python + uv) zum Arbeiten mit OpenAI-API-kompatiblen Modellen, mit zwei
initialen Features:

1. **Frage stellen:** `ai how to list all files in the current folder sorted by size`
   → streamt eine Antwort; erkennt vorgeschlagene Shell-Befehle und bietet Ausführung an.
2. **Terminal-Kontext lesen:** `ai -1 explain` → liest den vorherigen Befehl **inkl. dessen
   Ausgabe** aus dem Terminal und interpretiert die nachfolgende Anweisung ("explain") in
   diesem Kontext.

Entschiedene Rahmenbedingungen (mit Nutzer abgestimmt):
- Feature 2 nutzt **reine fish-Shell-Integration** (kein tmux-Zwang).
- Feature 1: **anzeigen + Ausführung anbieten** (y/n-Bestätigung).
- Konfiguration: **Env-Variablen + `~/.config/ai-cli/config.toml`** (Env überschreibt Config).
- Das Tool ist **shell-bewusst** (bash/zsh/fish): die erkannte Shell fließt in den Prompt ein,
  da Erklärungen/Befehle shell-abhängig sind.
- Zielplattform Linux; macOS soweit unkompliziert mitlaufend (Windows best effort).

### Zentrale technische Erkenntnis (prägt das Design)
Ein Prozess kann den Scrollback eines Terminals **nicht** nachträglich auslesen, und fish-Hooks
(`fish_preexec`/`fish_postexec`) sehen die **Ausgabe** eines Befehls nicht (sie geht direkt ans
TTY). Daher muss die Shell-Integration die Session mit `script(1)` aufzeichnen und mit
**OSC-Markern** Befehls-/Ausgabegrenzen kennzeichnen. Feature 2 parst dieses Typescript.

## Projektstruktur

```
ai-cli/
  pyproject.toml            # uv-Projekt, console-script "ai" -> ai_cli.cli:main
  README.md
  CHANGELOG.md              # gepflegtes Changelog (Keep a Changelog-Stil)
  plans/
    2026-06-24_001_Initial_Project.md   # dieser Plan, im Repo abgelegt
  .gitignore
  .python-version           # 3.14 (vorhanden: 3.14.4)
  src/ai_cli/
    __init__.py
    cli.py                  # Argument-Parsing, Dispatch
    config.py               # Env + TOML laden, Defaults
    client.py               # OpenAI-kompatibler Client (openai SDK), Streaming
    prompts.py              # System-Prompts (Shell-/OS-Kontext)
    shell.py                # Shell-Detection (fish/zsh/bash + Version/OS)
    ask.py                  # Feature 1: Frage stellen + Befehl ausführen anbieten
    context.py              # Feature 2: Typescript der Session parsen, N-letzten Block holen
    integration.py          # `ai install` / `ai init fish`: fish-Snippet ausgeben/installieren
    run.py                  # sichere Befehlsausführung mit Bestätigung
  shell/ai-cli.fish         # fish conf.d Snippet (Recording + OSC-Marker)
  tests/
    test_context_parse.py   # Typescript-Parser gegen Fixtures
    test_config.py
    test_cli_args.py
```

## Abhängigkeiten (via uv)
- `openai` — OpenAI-kompatibler Client (unterstützt `base_url`, Streaming).
- `rich` — gestreamtes Markdown-Rendering, Prompts/Bestätigung.
- `platformdirs` — Config-/Cache-Pfade (XDG, macOS/Windows-tauglich).
- stdlib: `tomllib` (3.11+ vorhanden), `argparse`, `re`, `base64`, `subprocess`.
- dev: `pytest`.

## CLI-Verhalten (`cli.py`)
- Argumentform: erstes Token kann ein **`-N`** sein (z. B. `-1`, `-2`) → Feature 2; sonst der
  gesamte Rest = freie Frage → Feature 1. (Eigene Vorab-Erkennung von `-N`, dann argparse,
  da `-1` sonst als unbekanntes Flag gilt.)
- Subcommands: `ai install [fish]`, `ai init fish` (Snippet auf stdout), `ai config` (zeigt
  aktive Konfig + Quelle).
- Beispiele:
  - `ai how to list files by size` → Feature 1.
  - `ai -1 explain` → liest letzten abgeschlossenen Befehlsblock, hängt "explain" als
    Nutzeranweisung an.
  - `ai -2 "why did this fail?"` → vorletzter Block.

## Feature 1 — Frage stellen (`ask.py`, `run.py`)
- System-Prompt (`prompts.py`) enthält erkannte **Shell + Version + OS** (aus `shell.py`),
  Anweisung knappe, shell-korrekte Antworten zu geben und Befehle in einem klar erkennbaren
  Format zu liefern (Code-Block mit Sprache `bash`/`fish`).
- Antwort wird via `rich` als Markdown gestreamt.
- Nach der Antwort: ist genau ein ausführbarer Befehl erkennbar (erster passender Code-Block),
  Prompt "Ausführen? [y/N]". Bei `y`: Ausführung in der aktiven Shell via `run.py`
  (`subprocess`, Befehl wird vor Ausführung nochmals angezeigt). Niemals automatisch ausführen.

## Feature 2 — Terminal-Kontext (`context.py` + Shell-Integration)

### Shell-Integration (`shell/ai-cli.fish`, ausgeliefert via `ai install`)
Wird einmalig nach `~/.config/fish/conf.d/` installiert (oder `ai init fish | source`).
Logik:
1. Nur interaktive Shells; Guard via Env `AI_CLI_RECORDING`, um Doppel-Recording zu vermeiden.
2. Beim Start (falls noch nicht aufgezeichnet): Session per `script` aufnehmen —
   `script -q -f -c fish $AI_CLI_LOG_DIR/<session-id>.typescript`, danach `exec`, sodass die
   neue fish-Instanz innerhalb der Aufzeichnung läuft. `AI_CLI_SESSION` (Pfad) + `AI_CLI_SHELL=fish`
   werden exportiert, damit `ai` die richtige Datei und Shell findet.
3. OSC-Marker (vom Terminal ignoriert, nicht sichtbar, aber im Typescript enthalten):
   - `fish_preexec`: `\e]1337;AICMD=<base64(cmd)>\a` gefolgt von `\e]133;C\a` (Output beginnt).
   - `fish_postexec`: `\e]133;D;$status\a` (Befehl fertig, Exit-Code).
   Damit ist jeder Befehlsblock eindeutig: Befehlstext (base64-dekodiert) + Output (Text
   zwischen `C` und `D`) + Exit-Code — ohne fragiles Prompt-Parsing.

### Parser (`context.py`)
- Liest `$AI_CLI_SESSION`-Typescript (Fallback: neueste Datei in `AI_CLI_LOG_DIR`).
- Splittet an den Markern in Blöcke `{cmd, output, exit}`; **ANSI-/Steuersequenzen strippen**.
- Verwirft den letzten, noch offenen Block (der laufende `ai`-Aufruf hat kein `D`).
- `-N` wählt den N-letzten **abgeschlossenen** Block.
- Output ggf. auf eine vernünftige Zeichenzahl kürzen (Tokens), Mitte elidieren.
- Fehlt eine aktive Aufzeichnung → klare Meldung: „Shell-Integration nicht aktiv, bitte
  `ai install` ausführen und Shell neu starten.“
- Der gewählte Block (Befehl + Output + Exit) wird als Kontext, die freie Anweisung
  ("explain", "why did this fail?") als Nutzerfrage an das Modell gegeben.

## Konfiguration (`config.py`)
- Reihenfolge (höchste Priorität zuerst): CLI-Flags > Env > TOML > Defaults.
- Env: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `AI_MODEL`.
- TOML `~/.config/ai-cli/config.toml` (via `platformdirs`):
  ```toml
  base_url = "https://api.openai.com/v1"
  model    = "gpt-4o-mini"        # Default; vom Nutzer anpassbar
  # api_key optional hier oder via Env
  ```
- `ai config` zeigt effektive Werte + Herkunft (ohne Key im Klartext).

## Shell-Detection (`shell.py`)
- Quelle in Reihenfolge: `AI_CLI_SHELL` (von Integration gesetzt) → Parent-Prozess
  (`/proc/<ppid>/comm` auf Linux) → `$SHELL`. Plus OS aus `platform`.
- Ergebnis (z. B. „fish 4.2.1 on Linux") fließt in den System-Prompt.

## Projektkonventionen (Nutzervorgabe)
- **Pläne** liegen immer unter `plans/` mit Schema `JJJJ-MM-TT_NNN_Kurzbeschreibung.md`
  (Datum, dreistelliger Zähler, knappe Beschreibung). Dieser Plan wird als
  `plans/2026-06-24_001_Initial_Project.md` ins Repo übernommen; künftige Pläne zählen weiter
  (`_002_`, …).
- **`CHANGELOG.md`** wird gepflegt (Keep-a-Changelog-Stil, `## [Unreleased]` + datierte
  Einträge). Erster Eintrag dokumentiert das initiale Setup + die beiden Features.
- Diese Konventionen werden zusätzlich in `CLAUDE.md`/Memory festgehalten, damit sie bei
  künftiger Arbeit automatisch greifen.

## Verifikation
1. `uv sync` → Projekt installiert; `uv run ai --help` zeigt Usage.
2. **Feature 1:** `OPENAI_API_KEY` (und ggf. `OPENAI_BASE_URL`) setzen, dann
   `uv run ai how to list files by size` → gestreamte Antwort + y/N-Prompt; bei `y` läuft der
   Befehl in fish.
3. **Feature 2 (Unit):** `pytest tests/test_context_parse.py` parst ein Typescript-Fixture mit
   OSC-Markern und liefert für `-1`/`-2` die korrekten `{cmd, output, exit}`-Blöcke.
4. **Feature 2 (E2E):** `ai install`, neue fish-Session starten, `ls -l` ausführen, dann
   `ai -1 explain` → erkennt `ls -l` inkl. „total 0"-Output und erklärt es.
5. `ai config` zeigt die aktive Konfiguration.

## Offene Implementierungsdetails (beim Bauen zu klären)
- Exakte Marker-Bytes / Robustheit des ANSI-Strippings gegen reale Programme (z. B. TUIs).
- Default-Modellname final (Platzhalter `gpt-4o-mini`, da Endpoint OpenAI-kompatibel/variabel).
