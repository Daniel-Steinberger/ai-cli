# ai-cli shell integration for fish.
#
# Records the interactive session with script(1) and emits invisible OSC markers
# around every command so that `ai -N <instruction>` can read a previous command,
# its output, and its exit code. The markers are terminal control sequences, so
# they are NOT shown on screen — they only appear inside the recorded typescript.
#
# Installed to ~/.config/fish/conf.d/ai-cli.fish by `ai install`, or load ad-hoc
# with:  ai init fish | source

if status is-interactive
    if set -q AI_CLI_RECORDING
        # We are already inside a recorded session: install the markers.
        # Custom OSC 1337 markers (AICMD / AIOUT / AIEND). We do NOT reuse OSC 133
        # because fish 4.x emits its own 133;A/C/D prompt markers, which would
        # collide and corrupt parsing.
        if type -q base64
            function __ai_cli_preexec --on-event fish_preexec
                set -l b64 (printf '%s' "$argv[1]" | base64 | tr -d '\n')
                printf '\x1b]1337;AICMD=%s\x07\x1b]1337;AIOUT\x07' $b64
            end
            function __ai_cli_postexec --on-event fish_postexec
                set -l st $status
                printf '\x1b]1337;AIEND=%s\x07' $st
            end
        end
    else if type -q script
        # Start recording, then re-exec fish inside it.
        set -q XDG_CACHE_HOME; and set -l base "$XDG_CACHE_HOME"; or set -l base "$HOME/.cache"
        set -l dir "$base/ai-cli/sessions"
        mkdir -p "$dir"

        # Housekeeping — runs once per real terminal launch (never inside the
        # recorded inner fish, which takes the branch above). Two jobs:
        #
        #  1. REAP orphaned recorders. setpriv --pdeathsig (below) only fires when
        #     the parent process actually dies. When a terminal/compositor restart
        #     leaves the pty unreadable but the parent process alive, script never
        #     gets the signal and busy-loops forever, ballooning its typescript to
        #     hundreds of GB. Such a recorder has been reparented to init / the
        #     systemd user manager, so a direct parent of pid 1 or comm `systemd`
        #     is our orphan signal (a healthy recorder's parent is the terminal
        #     emulator). HUP it and delete its runaway file.
        #  2. PRUNE leftovers: typescripts with no live writer that are >500 MiB
        #     or older than 14 days (there is otherwise no rotation). Files a live
        #     recorder still holds open are protected so we never unlink an
        #     in-progress session out from under `ai -N`.
        if type -q ps; and type -q pgrep
            set -l __ai_live
            for __ai_pid in (pgrep -u $USER -x script 2>/dev/null)
                set -l __ai_sess (ps -o args= -p $__ai_pid 2>/dev/null | string match -rg -- '(\S+\.typescript)')
                test -n "$__ai_sess"; and string match -q -- "$dir/*" "$__ai_sess"; or continue
                set -l __ai_ppid (ps -o ppid= -p $__ai_pid 2>/dev/null | string trim)
                set -l __ai_pcomm (ps -o comm= -p $__ai_ppid 2>/dev/null | string trim)
                if test "$__ai_ppid" = 1; or test "$__ai_pcomm" = systemd
                    kill -HUP $__ai_pid 2>/dev/null
                    rm -f "$__ai_sess" 2>/dev/null
                else
                    set -a __ai_live "$__ai_sess"
                end
            end
            if type -q find
                for __ai_f in (find "$dir" -maxdepth 1 -name '*.typescript' -type f \( -size +500M -o -mtime +14 \) 2>/dev/null)
                    contains -- "$__ai_f" $__ai_live; and continue
                    rm -f "$__ai_f" 2>/dev/null
                end
            end
        end

        set -gx AI_CLI_RECORDING 1
        set -gx AI_CLI_SHELL fish
        set -gx AI_CLI_SESSION "$dir/"(date '+%Y%m%d-%H%M%S')"-$fish_pid.typescript"
        # -f / -F flush after every write so `ai -N` sees the latest command
        # immediately (otherwise script block-buffers and recent output lags).
        #
        # On Linux, wrap script in `setpriv --pdeathsig HUP` so the recorder is
        # signalled to exit when its parent terminal process dies WITHOUT closing
        # the pty — e.g. a ptyxis-agent / terminal-emulator restart, crash, or a
        # compositor restart. In that case script is reparented to the user's
        # init manager and would otherwise linger forever, busy-looping on the
        # now-unreadable terminal (steady load, ~100% of one core, high sys time).
        # A clean Ctrl-D is unaffected: the parent stays alive and only this one
        # child exits normally. setpriv ships with util-linux alongside script;
        # fall back to bare script if it is somehow missing.
        if test (uname) = Darwin
            exec script -q -F "$AI_CLI_SESSION" fish
        else if type -q setpriv
            exec setpriv --pdeathsig HUP script -q -f -e -c fish "$AI_CLI_SESSION"
        else
            exec script -q -f -e -c fish "$AI_CLI_SESSION"
        end
    end
end
