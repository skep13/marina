#!/usr/bin/env python3
"""Write the desktop widget layout into Noctalia's settings.toml.

Noctalia rewrites settings.toml in its own layout, so instead of patching
lines this regenerates the whole [desktop_widgets] section. Run it with
Noctalia stopped (it overwrites the file when it exits):

  pkill -x noctalia; desktop-widgets.py; noctalia &
"""
import os

SETTINGS = os.path.expanduser("~/.local/state/noctalia/settings.toml")
OUTPUT = "eDP-1"
MOND = "Anurati"            # the Mond clock face; capitals only
BODY = "Inter"
MONO = "IBM Plex Mono"

GLASS = {
    "background": True,
    "background_color": "#10203d",
    "background_opacity": 0.55,
    "background_radius": 20.0,
    "background_padding": 16.0,
}
CLEAR = {"background": False, "shadow": False}


def toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(float(v)) if isinstance(v, float) else str(v)
    return '"' + str(v).replace('"', '\\"') + '"'


WIDGETS = [
    # id, type, cx, cy, box_w, box_h, settings
    ("day", "clock", 380, 185, 560, 82,
     {"format": "{:%^A}", "font_family": MOND, "color": "primary",
      "shadow": True, "background": False, "center_text": True}),
    ("date", "clock", 380, 258, 560, 30,
     {"format": "{:%d  %^B  %Y   ·   %H:%M}", "font_family": BODY,
      "color": "on_surface_variant", "center_text": True, **CLEAR}),

    # four square gauge tiles in a row
    *[(wid, "sysmon", 185 + i * 130, 375, 112, 112,
       {"display": "gauge", "gauge_layout": "vertical", "stat": stat,
        "font_family": MONO, **GLASS, "shadow": False})
      for i, (wid, stat) in enumerate([("cpu", "cpu_usage"), ("cputemp", "cpu_temp"),
                                       ("gputemp", "gpu_temp"), ("ram", "ram_pct")])],

    ("graph", "sysmon", 380, 560, 0, 0,
     {"display": "graph", "stat": "cpu_usage", "stat2": "ram_pct",
      "color": "primary", "color2": "secondary", "show_label": True,
      "font_family": MONO, **GLASS, "shadow": False}),

    ("media", "media_player", 380, 740, 0, 0,
     {"layout": "horizontal", "hide_when_no_media": True, "audio_visualizer": True,
      "album_art_background": True, "color": "on_surface", "font_family": MONO,
      **GLASS, "shadow": False}),
    ("viz", "audio_visualizer", 380, 880, 540, 64,
     {"bands": 48, "mirrored": True, "centered": True, "show_when_idle": False,
      "color_1": "primary", "color_2": "secondary", "background": False}),
]


def section():
    out = ["[desktop_widgets]", "enabled = true", "schema_version = 2",
           "widget_order = [ " + ", ".join(toml(w[0]) for w in WIDGETS) + " ]", "",
           "    [desktop_widgets.grid]", "    cell_size = 16", "    major_interval = 4",
           "    visible = true"]
    for wid, typ, cx, cy, bw, bh, settings in WIDGETS:
        out += ["", f"    [desktop_widgets.widget.{wid}]", f"    type = {toml(typ)}",
                f"    output = {toml(OUTPUT)}", f"    cx = {float(cx)}", f"    cy = {float(cy)}",
                f"    box_width = {float(bw)}", f"    box_height = {float(bh)}",
                "", f"        [desktop_widgets.widget.{wid}.settings]"]
        out += [f"        {k} = {toml(v)}" for k, v in settings.items()]
    return "\n".join(out) + "\n"


def main():
    s = open(SETTINGS).read()
    start = s.find("[desktop_widgets]")
    if start < 0:
        s = s.rstrip() + "\n\n" + section()
    else:
        nxt = s.find("\n[", start + 1)      # next top-level table (unindented)
        s = s[:start] + section() + (s[nxt:] if nxt >= 0 else "")
    open(SETTINGS, "w").write(s)
    print(f"wrote {len(WIDGETS)} widgets to {SETTINGS}")


if __name__ == "__main__":
    main()
