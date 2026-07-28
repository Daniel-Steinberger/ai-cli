# `@`-Referenzen für Dateien und Verzeichnisse

Ziel: `@pfad` im Chat (und im Print-Modus) referenziert eine Datei oder ein
Verzeichnis; Inhalt bzw. Listing wird der Nachricht als Kontext beigelegt. Die
Pfade werden im Popup vervollständigt, analog zu den Slash-Commands.

## Erkennung (`references.py`)

- Regex greift nur am Token-Anfang (Whitespace oder öffnende Klammer/Quote davor),
  damit `daniel@dvs.ag` oder `foo@bar` keine Referenz sind.
- Quoting für Pfade mit Leerzeichen: `@"my file.txt"`, `@'my file.txt'`.
- Satzzeichen am Ende (`@datei.py?`, `@datei.py,`, `(@datei.py)`) werden schrittweise
  abgeschnitten, bis der Pfad existiert.
- `~` wird expandiert; relative Pfade gelten zum aktuellen Verzeichnis.
- Nicht existierende Pfade sind kein Fehler: sie werden dem Nutzer gemeldet und
  bleiben als reiner Text in der Frage.

## Laden

| Fall | Verhalten |
|---|---|
| Datei | Inhalt, ab 100 KiB abgeschnitten (mit Hinweis im Text und in der Statuszeile) |
| Verzeichnis | Listing, Verzeichnisse zuerst und mit `/`, max. 200 Einträge |
| Binärdatei (`\0` im Inhalt) | nicht eingefügt, nur Hinweis |
| mehr als 10 Referenzen | Rest wird als `skipped` gemeldet, nicht still verworfen |
| doppelte Referenzen | über den aufgelösten Pfad dedupliziert |

Der Nutzer sieht vor der Antwort eine Statuszeile (`attached: @cli.py (4.2 KiB)`
bzw. `not attached: @weg.txt (not found)`) — es bleibt immer sichtbar, was
tatsächlich gesendet wurde.

## Einbindung

- `chat._run_turn` → `references.expand(text, console)`; pro Turn neu aufgelöst.
- `ask.ask` und `ask.explain` ebenfalls, damit `ai -p "@datei.py erklären"` und
  `ai -p -1 "vergleiche mit @datei.py"` gleich funktionieren.
- Prompt-Baustein `prompts.references_message()`.

## Vervollständigung

`chat._chat_completer` ersetzt den reinen Slash-Completer:

- Token am Zeilenanfang mit `/` → Slash-Commands (wie bisher).
- Token mit `@` an beliebiger Stelle → `PathCompleter` auf dem Teil nach dem `@`.
  Verzeichnisse bekommen ein `/` angefügt, damit das nächste Segment direkt
  weitervervollständigt wird; `display_meta` zeigt `file`/`directory`.
