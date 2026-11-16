# Paper theme for zsh. Prompt lives in ~/.oh-my-zsh/custom/themes/paper.zsh-theme.

# ls / completion colours in the same palette
export LS_COLORS='di=34:ln=36:ex=35:so=32:pi=33:bd=34;46:cd=34;43'
alias ls='ls --color=auto'
zstyle ':completion:*' list-colors 'di=34:ln=36:ex=35:so=32:pi=33'
zstyle ':completion:*' menu select

# Show what is eating RAM right now: `mem`
mem() {
  awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END {printf "\033[38;2;76;104;56mfree memory: %d%%\033[0m\n", a*100/t}' /proc/meminfo
  awk '/SwapTotal/{t=$2} /SwapFree/{f=$2} END {printf "\033[38;2;123;113;111mswap used:   %.0fM\033[0m\n", (t-f)/1024}' /proc/meminfo
  echo
  # group processes by name
  ps -eo rss=,comm= | awk '{m[$2]+=$1} END {for (k in m) printf "%7.0f MB  %s\n", m[k]/1024, k}' | sort -rn | head -12
}

# fastfetch with the braille logo of the wallpaper once per terminal window (not in nested shells)
if [[ -o interactive && -z $MIKU_FETCHED ]] && (( $+commands[fastfetch] )); then
  export MIKU_FETCHED=1
  fastfetch
fi
