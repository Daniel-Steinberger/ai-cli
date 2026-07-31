# Redraws nie aufzeichnen: script → FIFO → Filter → 10-MiB-Ring

Vorgabe: Bildschirm-Redraws sollen gar nicht in der Aufzeichnung landen, und die
Log-Datei soll nie größer als 10 MB werden.

## Architektur

```
fish
 └── script -q -f -e -c fish  ──►  <session>.fifo  ──►  ai _filter  ──►  <session>.typescript
                                                        (verwirft Steuersequenzen,
                                                         Ringpuffer 10 MiB)
```

`script` schreibt nicht mehr direkt in das Typescript, sondern in eine FIFO;
`ai _filter` (neu: `recorder.py`) ist der Leser und schreibt die Datei.

### Filter (`recorder.py`)

- `filter_bytes()` entfernt CSI-Sequenzen (Cursor, Farben, Redraws), fremde
  OSC-Sequenzen (Fenstertitel, fish' eigene OSC 133) und sonstige Escapes.
  **Erhalten** bleiben Klartext und unsere OSC-1337-Marker (`AICMD`/`AIOUT`/`AIEND`).
- Über Chunk-Grenzen geteilte Sequenzen werden zurückgehalten (`pending`), maximal
  8 KiB, damit ein langer `AICMD`-Marker (base64 des Kommandos) intakt bleibt.
- `RingWriter` hängt an und schneidet bei Überschreitung von `MAX_BYTES` (10 MiB)
  vorne ab, behält `KEEP_BYTES` (5 MiB) und setzt an einer Zeilengrenze auf.
  Überschreibbar per `AI_CLI_MAX_BYTES` / `AI_CLI_KEEP_BYTES`.

### Zwei harte Invarianten

1. **Lesen darf nie stoppen.** `script` blockiert, wenn der FIFO-Puffer voll ist —
   das würde die interaktive Shell einfrieren. Schreibfehler werden daher
   geschluckt (Daten verwerfen statt blockieren).
2. **Öffnen darf nie blockieren.** Die FIFO wird mit `O_NONBLOCK` geöffnet, der
   Filter schreibt danach ein `.ready`-Flag. fish wartet bis 2 s darauf und fällt
   sonst auf den direkten Schreibpfad zurück (sonst würde `script`'s `open()` auf
   eine leserlose FIFO warten und die Shell nie starten).

### Zwei Fehler, die im Test auffielen

- **EAGAIN ≠ EOF.** `os.read()` auf der non-blocking FIFO wirft `BlockingIOError`,
  wenn *gerade* keine Daten anliegen. Das wurde zunächst wie EOF behandelt: der
  Filter beendete sich sofort, `script` schrieb in eine leserlose FIFO und
  busy-loopte (Status `Rs`, Shell unbenutzbar). Jetzt endet der Filter nur, wenn
  der Parent (`script`) verschwunden ist, ein Signal kam, oder überhaupt nie ein
  Writer erschien (`STARTUP_TIMEOUT`).
- **`ESC ]` als 2-Byte-Escape.** Die Escape-Klasse `[@-Z\\-_]` enthält `]`, sodass
  ein am Chunk-Ende abgeschnittenes OSC als 2-Byte-Escape verworfen wurde und der
  base64-Rest als Text im Typescript landete. Klasse jetzt ohne `]`.
- **Unbekannte Escapes blockierten den Stream.** fish sendet um den Prompt `ESC =`
  und `ESC >` (Keypad-Modus). Diese matchten keine der bekannten Sequenzen, und die
  Regel „unvollständige Sequenz → zurückhalten“ hielt daraufhin *alles danach*
  zurück, bis 8 KiB erreicht waren: die Aufzeichnung blieb sichtbar bei 125 Bytes
  stehen, obwohl der Filter fleißig las. Zwei Änderungen:
  * `_SEQ` deckt jetzt DCS/PM/APC-Strings, Charset-Designationen (`ESC ( B`) und
    generisch jedes 2-Byte-Escape (`ESC` + druckbares Zeichen) ab.
  * Zurückgehalten wird nur, was mit mehr Eingabe *tatsächlich* noch eine Sequenz
    werden kann und am Chunk-Ende steht (`_INCOMPLETE` mit `\Z`) — ein einzelnes
    verirrtes ESC mitten im Chunk wird verworfen statt gepuffert.

  Gefunden über die neue Diagnose-Option `AI_CLI_FILTER_DEBUG=1` (Filter loggt
  gelesene Chunks nach stderr; die Shell leitet stderr sonst nach `/dev/null`).

### Absicherung, wenn der Filter stirbt

Beim Beenden schickt der Filter seinem Parent (`script`) `SIGHUP`, sofern er
tatsächlich dessen Senke war — eine beendete Session ist besser als ein
busy-loopendes Terminal. Greift bei SIGTERM/SIGHUP/normalem Ende, **nicht** bei
`SIGKILL`/OOM: dann bleibt die bekannte Restlücke (script busy-loopt, bis das
Housekeeping beim nächsten Shell-Start es einsammelt).

### Housekeeping

- Live-Erkennung matcht jetzt `*.typescript` **und** `*.fifo` in der
  `script`-Kommandozeile (sonst würde eine laufende Session als tot gelten).
- Verwaiste FIFOs samt `.ready` werden beim Shell-Start entfernt.
- Der `fallocate`-Wächter aus 006 bleibt als Netz für den Fallback-Pfad, greift
  aber nicht mehr, wenn der Filter läuft (`AI_CLI_FILTERED`). Limit dort ebenfalls
  10 MiB / 5 MiB.

## Verifikation (echtes PTY, isoliertes `XDG_CONFIG_HOME`)

| Prüfung | Ergebnis |
|---|---|
| Shell-Start mit Filter | Prompt < 1 s, `AI_CLI_FILTERED=1` |
| 8000 Redraw-Sequenzen | Typescript **9,3 KB**, **0** CSI-Sequenzen |
| Marker/Parsing | `AICMD` erhalten, `get_blocks(2)` liefert Kommando + Output |
| Session-Ende | FIFO und `.ready` gelöscht, nur Typescript bleibt |
| Filter getötet (SIGTERM) | Parent bekommt SIGHUP (Unit-Test) |
