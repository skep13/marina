# Paper: oh-my-zsh theme matching the wallpaper (sage eyes, crimson marks, ink greys)
ZSH_THEME_GIT_PROMPT_PREFIX=" %F{#7b716f}on%f %F{#8a6d2b}"
ZSH_THEME_GIT_PROMPT_SUFFIX="%f"
ZSH_THEME_GIT_PROMPT_DIRTY=" %F{#a43c35}✗%f"
ZSH_THEME_GIT_PROMPT_CLEAN=""

# ✦ dir on branch
# ❯
PROMPT=$'\n%F{#4c6838}✦%f %F{#3a312b}%B%~%b%f$(git_prompt_info)\n%(?.%F{#4c6838}.%F{#a43c35})❯%f '
RPROMPT='%F{#a6a4a6}%*%f'
