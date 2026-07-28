# 2026-07-28_003 — Session Recorder Cleanup (Reaper + Pruning)

## Problem
`~/.cache/ai-cli/sessions` had grown to **603 GB**. Three orphaned `script(1)`
recorders from Jul 24 were still running with dead controlling terminals
(pts/2, /5, /7 — nobody logged in); one busy-looped (37 min CPU) and had inflated
its typescript to 353 GB and was still growing.

The existing guard `setpriv --pdeathsig HUP` (commit 4147fbf) was installed and
active, yet the orphans survived. Root cause: `PR_SET_PDEATHSIG` only fires when
the **parent process itself dies**. On a terminal/compositor restart where the
pty becomes unreadable but the parent process stays alive, `script` never gets
the signal and busy-loops forever. There was also **no rotation** — typescripts
accumulated without bound.

## Immediate remediation (done)
- HUP'd the 5 orphaned processes (2 recorders + a stale one + 2 child fish).
- Deleted the 3 runaway typescripts → **602 GB freed** (folder now 79 MB).
- Left the 4 active same-day sessions untouched.

## Permanent fix — `src/ai_cli/data/ai-cli.fish`
Housekeeping block runs once per real terminal launch (outer, non-recording
branch), guarded on `ps`/`pgrep`/`find`:

1. **Reaper** — for each of our `script` recorders (args path under the sessions
   dir), if its direct parent is pid 1 or comm `systemd`, it has been reparented
   → orphan. `kill -HUP` it and `rm -f` its typescript. Healthy recorders (parent
   = terminal emulator, e.g. `ptyxis-agent`) are left alone and recorded as live.
2. **Pruning** — delete typescripts with no live writer that are `>500 MiB` or
   `mtime +14` days. Live files (held open by a healthy recorder) are protected
   via a skip-list so an in-progress session is never unlinked under `ai -N`.

## Verification
- `fish -n` syntax check passes.
- Path extraction, size/age prune, and live-file protection tested in a temp dir.
- Reaper classification run read-only against real processes: all 4 live
  recorders correctly classified healthy (parents `ptyxis-agent`/`sh`), none
  flagged for reaping.

## Notes / follow-ups
- The 500 MiB / 14 day thresholds are conservative; a normal session is KB–MB.
- Detection is cross-platform-friendly: macOS orphans reparent to launchd (pid 1)
  and are also caught, though the busy-loop itself is a Linux `script(1)` issue.
- Reminder: the shipped `ai-cli.fish` is package data — reinstall
  (`uv tool install . --reinstall`) / `ai install` to propagate to a user's
  `~/.config/fish/conf.d/ai-cli.fish`.
