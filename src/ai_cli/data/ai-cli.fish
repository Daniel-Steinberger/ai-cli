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
        if type -q base64
            function __ai_cli_preexec --on-event fish_preexec
                set -l b64 (printf '%s' "$argv[1]" | base64 | tr -d '\n')
                printf '\x1b]1337;AICMD=%s\x07\x1b]133;C\x07' $b64
            end
            function __ai_cli_postexec --on-event fish_postexec
                set -l st $status
                printf '\x1b]133;D;%s\x07' $st
            end
        end
    else if type -q script
        # Start recording, then re-exec fish inside it.
        set -q XDG_CACHE_HOME; and set -l base "$XDG_CACHE_HOME"; or set -l base "$HOME/.cache"
        set -l dir "$base/ai-cli/sessions"
        mkdir -p "$dir"
        set -gx AI_CLI_RECORDING 1
        set -gx AI_CLI_SHELL fish
        set -gx AI_CLI_SESSION "$dir/"(date '+%Y%m%d-%H%M%S')"-$fish_pid.typescript"
        if test (uname) = Darwin
            exec script -q "$AI_CLI_SESSION" fish
        else
            exec script -q -e -c fish "$AI_CLI_SESSION"
        end
    end
end
