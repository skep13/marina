-- AI workstation bindings and rules for Hyprland (Caelestia).
-- Loaded from ~/.config/caelestia/hypr-user.lua by one line that setup.sh
-- adds:   dofile("/usr/share/aiws/hypr/aiws.lua")
-- Caelestia's own files aren't touched, so `caelestia update` keeps working.
--
--   Super+Space    open / close Marina (the sphere's chat)
--   Super+Escape   stop the assistant now
--   Super+A        AI Control Centre      (Super+C is Caelestia's editor)

hl.on("hyprland.start", function()
    hl.exec_cmd("/usr/lib/aiws/session-setup")
    hl.exec_cmd("aiws-orb")                -- Marina's sphere, bottom-right
end)

hl.bind("SUPER + SPACE", hl.dsp.exec_cmd("aiws-orb --toggle"))
hl.bind("SUPER + ESCAPE", hl.dsp.exec_cmd("ai agent stop"))
hl.bind("SUPER + A", hl.dsp.exec_cmd("aiws-control"))

-- The Ask popup: small, floating, above everything, centred.
hl.window_rule({ match = { class = "ai-ask" }, float = true, pin = true, center = true,
                 size = "(monitor_w*0.4) (monitor_h*0.45)", opacity = "1 override" })
-- Control Centre: a floating panel.
hl.window_rule({ match = { class = "aiws-control" }, float = true, center = true,
                 size = "(monitor_w*0.62) (monitor_h*0.72)" })
-- Marina's sphere: floating, on every workspace, no frame, no blur or
-- dimming, fully opaque so the transparent window shows only the sphere.
-- Starts in the bottom-right corner; the app re-anchors it when it grows.
hl.window_rule({ match = { title = "^Marina$" }, float = true, pin = true,
                 no_shadow = true, no_blur = true, no_dim = true, rounding = 0,
                 no_initial_focus = true, opacity = "1 override",
                 move = "(monitor_w-window_w-18) (monitor_h-window_h-18)" })
