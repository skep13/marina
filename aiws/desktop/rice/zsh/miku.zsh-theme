# Miku — oh-my-zsh theme matching the wallpaper palette
ZSH_THEME_GIT_PROMPT_PREFIX=" %F{#3D4F8B}on%f %F{#A58BE0}"
ZSH_THEME_GIT_PROMPT_SUFFIX="%f"
ZSH_THEME_GIT_PROMPT_DIRTY=" %F{#E07A9A}✗%f"
ZSH_THEME_GIT_PROMPT_CLEAN=""

# ✿ dir on branch
# ❯
PROMPT=$'\n%F{#7B8FE0}✿%f %F{#C4CDF2}%B%~%b%f$(git_prompt_info)\n%(?.%F{#627DC7}.%F{#E07A9A})❯%f '
RPROMPT='%F{#3D4F8B}%*%f'
