# Interaktiver Modus als Default + Slash-Commands

Ziel: `ai` verhält sich wie `claude` — ohne Flag landet man im interaktiven Chat,
`-p/--print` erzwingt die einmalige Ausgabe. Im Chat gibt es Slash-Commands mit
Live-Autovervollständigung (Omnibar-Stil) inklusive Kurzbeschreibung.

## Verhalten (CLI)

| Aufruf | vorher | nachher |
|---|---|---|
| `ai` | Usage | interaktiver Chat |
| `ai <frage>` | one-shot | Chat, Frage als erster Turn |
| `ai -p <frage>` | – | one-shot (Feature 1) |
| `ai -N [text]` | one-shot explain | Chat mit den letzten N Kommandos als Kontext |
| `ai -p -N [text]` | – | one-shot explain (Feature 2) |
| `… \| ai <frage>` | one-shot | Chat mit piped Kontext (stdin → `/dev/tty`) |
| `ai -h`, `install`, `init`, `config` | unverändert | unverändert |

- `-i/--interactive` bleibt als No-Op-Alias erhalten (Rückwärtskompatibilität).
- Ohne nutzbares Terminal (kein TTY, z. B. `ai frage > out.txt` oder in Skripten)
  wird automatisch auf den Print-Modus zurückgefallen, statt zu scheitern.

## Slash-Commands

Registry in `commands.py`: Name, Usage-Hinweis, Beschreibung, Handler.

- `/help` — alle Commands mit Beschreibung
- `/clear` — Verlauf löschen (Bildschirm ebenfalls); der geladene Kontext bleibt,
  da er Teil des System-Prompts ist
- `/exit` — Chat beenden (wie `^D`/`exit`)
- `/model [name]` — Modell anzeigen bzw. für die laufende Session umschalten
- `/config` — effektive Konfiguration (gleiche Tabelle wie `ai config`)
- `/context [-N]` — die letzten N Kommandos + Output nachträglich in die Session laden

Eingaben, die mit `/` beginnen, aber kein bekannter Command sind (z. B.
`/tmp/foo — was ist das?`), gehen als normale Frage ans Modell.

## Autovervollständigung

`prompt_toolkit` ersetzt `readline` im Chat: `Completer`, der nur beim ersten Token
und nur bei führendem `/` greift, mit `display_meta` = Beschreibung. Menü klappt
beim Tippen auf (`complete_while_typing`, `CompleteStyle.COLUMN`). Fehlt
prompt_toolkit, greift der bisherige readline/`input()`-Pfad ohne Menü.

## Struktur

- `session.py` (neu) — `ChatSession`: config/console/shell, System-Prompt, Messages,
  `reset()`, `add_context()`. Vermeidet einen Zyklus zwischen `chat` und `commands`.
- `commands.py` (neu) — Registry + `dispatch()` + `completions()`; enthält auch
  `render_config()`, das `cli.py` für `ai config` mitbenutzt.
- `chat.py` — Eingabe über `_build_input()` (prompt_toolkit oder Fallback),
  Command-Dispatch vor dem Modellaufruf.
- `cli.py` — `-p` extrahieren, Default-Dispatch umdrehen, USAGE neu.
