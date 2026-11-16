# Night prompt for fish: colours from the wallpaper (blue flowers, crimson gem, brass staff).
# Works in light and dark mode: the folder uses the terminal's own text colour,
# the accents are mid-tones that read on either background.
#   ✦ ~/dir on branch ✗
#   ❯
function fish_prompt
    set -l last $status
    echo
    set_color 7f9cff; printf '✦ '
    set_color --bold 9fb4ff; printf '%s' (prompt_pwd --full-length-dirs 2)
    set_color normal
    set -l branch (command git symbolic-ref --short HEAD 2>/dev/null; or command git rev-parse --short HEAD 2>/dev/null)
    if test -n "$branch"
        set_color 5b6aa8; printf ' on '
        set_color a6916b; printf '%s' $branch
        if test -n "$(command git status --porcelain 2>/dev/null | head -1)"
            set_color e04a5c; printf ' ✗'
        end
    end
    echo
    if test $last -eq 0; set_color 7f9cff; else; set_color e04a5c; end
    printf '❯ '
    set_color normal
end
