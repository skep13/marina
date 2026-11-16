# Paper prompt for fish: colours from the wallpaper (sage eyes, crimson marks, brass staff).
# Works in light and dark mode: the folder uses the terminal's own text colour,
# the accents are mid-tones that read on either background.
#   ✦ ~/dir on branch ✗
#   ❯
function fish_prompt
    set -l last $status
    echo
    set_color 6f9a5a; printf '✦ '
    set_color --bold normal; printf '%s' (prompt_pwd --full-length-dirs 2)
    set_color normal
    set -l branch (command git symbolic-ref --short HEAD 2>/dev/null; or command git rev-parse --short HEAD 2>/dev/null)
    if test -n "$branch"
        set_color 8a8280; printf ' on '
        set_color b39a4f; printf '%s' $branch
        if test -n "$(command git status --porcelain 2>/dev/null | head -1)"
            set_color c0534b; printf ' ✗'
        end
    end
    echo
    if test $last -eq 0; set_color 6f9a5a; else; set_color c0534b; end
    printf '❯ '
    set_color normal
end
