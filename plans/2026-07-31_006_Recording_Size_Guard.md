# MemoryError bei `ai -N` + unbegrenzt wachsende Recordings

## Symptom

```
ai -1 remote command ausführen
  …/context.py", line 117, in read_session_text
    return path.read_text(encoding="utf-8", errors="replace")
MemoryError
```

Die aktive Session war **84,5 GiB** groß und wuchs mit ~1,5 MB/s weiter.

## Ursache

Zwei unabhängige Fehler:

1. `read_session_text()` las das komplette Typescript in den Speicher. Für `ai -N`
   werden aber nur die *letzten* Kommandos gebraucht, die am Dateiende stehen.
2. Der Recorder (`script -f`) zeichnet jeden Bildschirm-Redraw auf. Ein
   Full-Screen-Programm (Editor, TUI, `claude`) zeichnet dauernd neu — der Inhalt
   am Dateiende bestand aus Millionen von `ESC[64;185H`-Cursor-Sequenzen. Der
   Recorder war *gesund* (Parent lebt), also griff weder das Orphan-Reaping noch
   das Prune (das nur Dateien ohne lebenden Schreiber löscht).

## Fix 1 — Tail-Read (`context.py`)

`read_session_text()` liest ab jetzt nur ein Fenster am Dateiende: Start bei 8 MiB,
Verdopplung bis ein abgeschlossenes Kommando (`AIEND`-Marker) enthalten ist,
maximal 64 MiB. Findet sich darin kein Kommando, gibt es statt eines Tracebacks
eine erklärende Meldung („… a full-screen program most likely flooded it …“).

Alle Aufrufer fangen jetzt `context.CONTEXT_ERRORS`
(`NoSessionError | ValueError | OSError | MemoryError`) — ein Lesefehler darf nie
mehr als Traceback durchschlagen.

Verifiziert an der echten 84,5-GiB-Datei: 0,33 s bis zur Meldung statt MemoryError.

## Fix 2 — Größenwächter (`data/ai-cli.fish`)

Neuer `fish_postexec`-Handler: übersteigt die **belegte** Größe der eigenen Session
512 MiB, wird per `fallocate --punch-hole` der vordere Teil freigegeben und nur der
letzte 32-MiB-Block behalten.

Warum punch-hole und nicht truncate: `script` schreibt sequenziell mit steigendem
Offset (kein `O_APPEND`). Ein `truncate -s 0` würde nichts freigeben, der Offset
bliebe hoch. Das Loch gibt die Blöcke frei, lässt den Schreib-Offset unberührt und
erhält den Tail — genau den Teil, den `ai -N` liest. Der Rest liest sich als
Nullbytes, was der Parser ohnehin ignoriert (Blöcke ohne `AICMD` verfallen).

Limits per `AI_CLI_MAX_BYTES` / `AI_CLI_KEEP_BYTES` überschreibbar. Linux-only
(`fallocate`); ohne fallocate/du/stat wird der Handler nicht definiert.

Interaktiv im PTY verifiziert: 42 MB → 4,2 MB belegt, Tail intakt, `$status` wird
korrekt an den Prompt durchgereicht (fish sichert `$status` um Event-Handler).

## Sofortmaßnahme

Die laufende 84,5-GiB-Datei wurde mit demselben punch-hole behandelt: belegt jetzt
33 MiB, Recorder läuft weiter, `df` von 380G auf 296G belegt.

## Bekannte Restlücke

Der Wächter greift erst *nach* einem Kommando. Läuft ein TUI stundenlang, wächst
die Datei während dieser Zeit unbegrenzt und wird erst beim Beenden getrimmt. Eine
echte Lösung wäre ein Ringpuffer-Writer statt einer Datei (`script` in eine Pipe,
Filter behält die letzten N MiB) — größerer Umbau der Integration, bewusst nicht
Teil dieses Fixes.
