# Plan: Interaktiver Chat-Modus (`ai -i`)

## Context

Das `ai`-CLI (Python + uv, in `/home/dst/src/ai-cli`) hat bereits zwei Features: freie
Frage (`ai <frage>`) und Terminal-Kontext (`ai -N <anweisung>`). Beide sind **Einmal-
Anfragen** (ein Request, eine Antwort, fertig).

Gewünscht ist ein **interaktiver Chat-Modus** über die Flag `-i`:
- `ai -i` startet einen mehrstufigen Chat (Verlauf bleibt über Turns erhalten).
- Verlassen mit **^D** (EOF), sowie Befehlen wie `exit`, `quit`, `bye`, `q`, `:q`.
- Wird zusätzlich `-N` und/oder freier Text angegeben, geht das als **Anfangskontext** in
  den Chat ein: `ai -i -3 "warum schlug das fehl?"` startet den Chat mit den letzten 3
  Befehlen als Kontext und der Frage als erstem Turn.

Mit dem Nutzer abgestimmt:
- **Eingabe-Bibliothek: stdlib `readline`** — keine neue Abhängigkeit. `input()` +
  `import readline` liefert ^D (EOFError), Zeilen-Editing und History.
- **Befehlsausführung im Chat: ja, wie Feature 1** (y/N-Prompt), aber zusätzlich wird die
  **Ausgabe des Befehls automatisch in den Chat zurückgespeist**, sodass das Modell darauf
  reagieren kann. **Wichtig:** sudo wird häufig vorkommen → verdeckte Passworteingabe muss
  funktionieren.

### Zentrale technische Erkenntnis (Ausgabe mitschneiden + sudo verdeckt)
Damit die Ausgabe gleichzeitig **live am Bildschirm** erscheint **und** für den Chat
**mitgeschnitten** wird, läuft der Befehl im Chat über ein **PTY** (`pty.spawn`, stdlib):
- `pty.spawn(argv, master_read=...)` leitet die Terminal-Ein-/Ausgabe durch; im
  `master_read`-Callback schreiben wir die Bytes nach stdout **und** in einen Puffer.
- `sudo` liest sein Passwort von der PTY mit abgeschaltetem Echo → es erscheint weder am
  Bildschirm noch im Mitschnitt (kein Passwort-Leak in den Chat).
- Der Mitschnitt wird mit dem vorhandenen `context.strip_ansi` von Steuersequenzen bereinigt
  und längenbegrenzt (Elision wie bei `context._elide`), bevor er als Nachricht zurückgeht.

Der **Feature-1-Einmalpfad** bleibt unverändert (`subprocess.run`, kein Capture) — dort gibt
es keinen Folge-Turn, in den man etwas zurückspeisen könnte.

## Abhängigkeiten
**Keine neuen.** `readline` und `pty` sind CPython-stdlib (Linux/macOS — exakt die
Zielplattform). Streaming/Rendering deckt das vorhandene `rich` ab. (Windows: `readline`/`pty`
fehlen → Fallback: einfaches `input()` bzw. `subprocess.run` ohne Capture.)

## Umsetzung

### 1. `client.py` — Mehr-Turn-Streaming
- Neue Funktion `stream_messages(config, messages: list[dict]) -> Iterator[str]`, die eine
  vollständige Nachrichtenliste streamt (gleiche Fehlerbehandlung wie bisher).
- `stream_chat(config, system, user)` baut die 2-Element-Liste und delegiert an
  `stream_messages` (Verhalten unverändert, kein Bruch für ask/explain).

### 2. `ask.py` — Render-Helfer wiederverwendbar machen
- `_stream_and_render` so umstellen, dass es eine **messages-Liste** entgegennimmt und
  `stream_messages` nutzt; öffentlich als `render_stream(config, messages, console) -> str`
  exportieren. `ask()`/`explain()` bauen weiterhin ihre 2-Element-Liste.

### 3. `prompts.py` — Chat-Prompt + Block-Formatierung extrahieren
- `format_blocks(blocks) -> str` aus `explain_user_prompt` herauslösen (DRY); beide nutzen es.
- `chat_system_prompt(shell) -> str`: konversationelle, shell-bewusste System-Anweisung;
  Befehlsvorschläge weiterhin in ```{shell_name}-Codeblöcken (damit `offer_to_run` sie
  extrahieren kann).
- `command_result_message(cmd, output, exit_code) -> str`: formatiert ein ausgeführtes
  Befehlsergebnis als User-Nachricht, die ins Gespräch zurückgespeist wird.

### 3b. `run.py` — Capture-Runner für den Chat
- Gemeinsamen Bestätigungsteil herauslösen: `_confirm_and_get_argv(answer, shell, console)
  -> list[str] | None` (nutzt vorhandene `extract_command`, `Syntax`-Anzeige, `Confirm`,
  `_shell_exec_argv`).
- `offer_to_run` (Feature 1, unverändert im Verhalten) nutzt diesen Helfer + `subprocess.run`.
- **Neu** `offer_to_run_capture(answer, shell, console) -> tuple[str, str, int] | None`:
  Bestätigung wie oben; bei Ausführung den Befehl via PTY laufen lassen (`master_read`-Tee:
  stdout + Puffer), Rückgabe `(command, captured_output_clean, exit_code)` oder `None`.
  Verwendet `context.strip_ansi` und Längenbegrenzung.

### 4. `chat.py` (neu) — REPL
- `chat(config, console, shell, blocks=None, initial_text=None) -> int`:
  - `readline`-History-Datei unter `config.log_dir().parent / "chat_history"` (try/except;
    bei `ImportError` ohne readline weiterlaufen).
  - System-Prompt = `chat_system_prompt(shell)`; falls `blocks`: `format_blocks` als
    Kontextabschnitt anhängen. `messages = [system]`.
  - Banner ausgeben (Modell, Hinweis „^D oder 'exit' zum Beenden").
  - Falls `initial_text`: als ersten User-Turn behandeln.
  - Schleife: Prompt via `console.input("…› ")`; **^D → EOFError → beenden**;
    **^C → KeyboardInterrupt → aktuelle Zeile abbrechen, weiter**; leere Zeile überspringen;
    Eingabe in `EXIT_WORDS = {exit, quit, bye, q, :q}` (case-insensitive) → beenden.
  - **Turn-Verarbeitung** (`_turn`): user anhängen → `render_stream` → assistant anhängen →
    `offer_to_run_capture`. Liefert es `(cmd, output, exit)` zurück, wird ein **User-Turn mit
    dem Befehlsergebnis** (`prompts.command_result_message`) angehängt und **automatisch eine
    weitere Assistant-Antwort gestreamt**; das wiederholt sich, solange das Modell einen
    Befehl vorschlägt und der Nutzer mit y bestätigt (jeder Schritt ist durch y/N gated, also
    keine unkontrollierte Schleife).
  - Beim Beenden History schreiben + Abschiedszeile.

### 5. `cli.py` — Flag `-i` + Dispatch
- `_extract_options` zusätzlich `-i`/`--interactive` (an beliebiger Position) erkennen →
  Rückgabe wird `(model, debug, interactive, rest)`. Aufrufer + Tests anpassen.
- In `main`: wenn `interactive`:
  - Falls `rest[0]` ein `-N` ist → `blocks = get_blocks(N)` (bei `NoSessionError`/`ValueError`
    Warnung ausgeben und **ohne** Kontext weiterchatten); restliche Strings = `initial_text`.
  - Sonst: gesamter `rest` (falls vorhanden) = `initial_text`, keine Blöcke.
  - `chat.chat(config, console, detect_shell(), blocks, initial_text or None)` aufrufen.
  - `ai -i` mit leerem `rest` startet den Chat ohne Kontext (nicht die Usage anzeigen).
- USAGE-Text um `-i` ergänzen.

## Zu ändernde/erstellende Dateien
- `src/ai_cli/chat.py` (neu)
- `src/ai_cli/cli.py` (Flag, Dispatch, Usage)
- `src/ai_cli/client.py` (`stream_messages`)
- `src/ai_cli/ask.py` (`render_stream`)
- `src/ai_cli/run.py` (`_confirm_and_get_argv`, `offer_to_run_capture` via PTY)
- `src/ai_cli/prompts.py` (`format_blocks`, `chat_system_prompt`, `command_result_message`)
- `tests/test_cli_args.py` (4-Tupel, `-i`-Kombinationen)
- `tests/test_chat.py` (neu): `EXIT_WORDS`-Erkennung; Loop mit gemocktem `render_stream`,
  `input` und `offer_to_run_capture` — Fall ohne Befehl (Eingaben `["hallo","exit"]` → ein
  Modell-Call) und Fall mit zurückgespeistem Befehlsergebnis (mockt Capture → prüft, dass ein
  zweiter Assistant-Turn mit dem Ergebnis in `messages` folgt); `format_blocks`/
  `command_result_message`-Ausgabe. (PTY-Capture selbst wird manuell verifiziert, s. u.)
- `README.md`, `CHANGELOG.md`.
- Plan zusätzlich als `plans/2026-06-24_002_Interactive_Mode.md` ins Repo übernehmen
  (Projektkonvention: `plans/` + Zähler; siehe `CLAUDE.md`).

## Verifikation
1. `uv run pytest -q` → alle Tests grün (inkl. neuer Chat-/CLI-Tests).
2. **Chat manuell:** `uv run ai -i` → Banner; eine Frage stellen → gestreamte Antwort;
   `exit` und separat **^D** beenden sauber.
3. **Kontext:** in aufgezeichneter fish-Session `ls -l` ausführen, dann `uv run ai -i -1`
   → Chat kennt `ls -l` + Ausgabe; Folgefrage „und sortiert nach Größe?" greift den Kontext auf.
4. **Befehl + Rückspeisung:** im Chat nach einem Befehl fragen (z. B. „zeig die 3 größten
   Dateien hier"); bei y läuft er, die Ausgabe erscheint live **und** das Modell kommentiert
   sie anschließend automatisch (Ausgabe wurde zurückgespeist).
5. **sudo:** nach einem Befehl mit sudo fragen; bei y die **verdeckte** Passwortabfrage prüfen
   (kein Echo am Bildschirm, Passwort nicht im zurückgespeisten Text).
6. `ai -i -3 --debug "fasse zusammen"` startet Chat mit 3 Blöcken als Kontext (Optionen an
   beliebiger Position).

## Bewusst nicht in v1
- `prompt_toolkit`-Komfort (persistente Suche, Mehrzeilen) — bewusst zugunsten „keine neue
  Dependency" verworfen.
