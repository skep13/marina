# ====================================================================
#  Songbird Pi - tell the OLED front panel what the shell is doing.
#  Installed as /etc/profile.d/songbird-jobs.sh (interactive bash only).
#
#  A command running longer than a few seconds shows on the panel with a
#  timer; one that took 10 s or more leaves a "done" / "failed" card and a
#  line in the panel's recent-jobs history.
#  Interactive programs (editors, ssh, top...) are left alone.
# ====================================================================
if [ -n "$BASH_VERSION" ] && [[ $- == *i* ]] && [ -d /run/songbird-oled ]; then
    __sb_dir=/run/songbird-oled
    __sb_skip=' vi vim nvim nano less more man top htop btop ssh mosh tmux screen watch tail journalctl clear exit '
    __sb_ready=

    # DEBUG fires before every simple command; only the first one after a
    # prompt (when __sb_ready is set) starts timing the line you typed.
    __sb_start() {
        [ -n "$__sb_ready" ] || return
        __sb_ready=
        [ -n "$COMP_LINE" ] && return
        local first=${BASH_COMMAND%% *}
        [[ $__sb_skip == *" ${first##*/} "* ]] && return
        local line
        line=$(HISTTIMEFORMAT= builtin history 1)
        line=${line#*[0-9]  }
        __sb_cmd=${line:-$BASH_COMMAND}
        __sb_t0=$SECONDS
        printf '%s\n%s\n' "$(date +%s)" "$__sb_cmd" > "$__sb_dir/job.$$" 2>/dev/null
    }

    __sb_end() {
        local rc=$?
        if [ -n "$__sb_cmd" ]; then
            local took=$((SECONDS - __sb_t0))
            rm -f "$__sb_dir/job.$$"
            if [ "$took" -ge 10 ]; then
                printf '%s\n%s\n%s\n%s\n' "$(date +%s)" "$rc" "$took" "$__sb_cmd" > "$__sb_dir/note" 2>/dev/null
                printf '%s\t%s\t%s\t%s\n' "$(date +%s)" "$rc" "$took" "${__sb_cmd//$'\t'/ }" >> "$__sb_dir/history" 2>/dev/null
            fi
        fi
        __sb_cmd=
        return $rc
    }

    trap '__sb_start' DEBUG
    PROMPT_COMMAND="__sb_end${PROMPT_COMMAND:+; $PROMPT_COMMAND}; __sb_ready=1"
fi
