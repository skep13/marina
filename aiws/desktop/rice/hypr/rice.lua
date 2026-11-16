-- The Miku rice on Hyprland/Caelestia: Rectangle's shortcuts, the Mond
-- clock, kitty. Loaded from ~/.config/caelestia/hypr-user.lua by:
--   dofile(os.getenv("HOME") .. "/.config/miku-theme/rice.lua")
--
-- Rectangle on the Mac uses Ctrl+Option; here it's Ctrl+Alt.
--   Ctrl+Alt+←/→/↑/↓   halves            Ctrl+Alt+U/I/J/K   quarters
--   Ctrl+Alt+D/F/G      thirds            Ctrl+Alt+E/T       two-thirds
--   Ctrl+Alt+Return     maximise          Ctrl+Alt+C         centre
--   Ctrl+Alt+Backspace  back to tiling

local snap = os.getenv("HOME") .. "/.local/bin/snap-window "

local binds = {
    ["CTRL + ALT + LEFT"]   = "left",
    ["CTRL + ALT + RIGHT"]  = "right",
    ["CTRL + ALT + UP"]     = "top",
    ["CTRL + ALT + DOWN"]   = "bottom",
    ["CTRL + ALT + U"]      = "tl",
    ["CTRL + ALT + I"]      = "tr",
    ["CTRL + ALT + J"]      = "bl",
    ["CTRL + ALT + K"]      = "br",
    ["CTRL + ALT + D"]      = "first-third",
    ["CTRL + ALT + F"]      = "center-third",
    ["CTRL + ALT + G"]      = "last-third",
    ["CTRL + ALT + E"]      = "first-two-thirds",
    ["CTRL + ALT + T"]      = "last-two-thirds",
    ["CTRL + ALT + RETURN"] = "max",
    ["CTRL + ALT + C"]      = "center",
    ["CTRL + ALT + BACKSPACE"] = "restore",
}
for key, pos in pairs(binds) do
    hl.bind(key, hl.dsp.exec_cmd(snap .. pos))
end

hl.on("hyprland.start", function()
    hl.exec_cmd("qs -c mond -d")           -- the Mond clock on the desktop
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/aiws-firstlogin")  -- once only
end)
