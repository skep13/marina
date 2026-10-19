#!/usr/bin/env python3
"""Generate uplink-host-b42.css: a per-host layer for the homelab's existing
`uplink-pve-theme` system that re-skins uplink to the B42 look.

The uplink script concatenates this file AFTER uplink.css into the served
/pve2/css/uplink.css and version-fingerprints the link, so it overrides
uplink on equal specificity, busts the browser cache, and survives
pve-manager upgrades. Install as /usr/local/share/uplink-pve/uplink-host.css
on each node, then run /usr/local/sbin/uplink-pve-theme."""
import base64, os

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "assets", "proxmox-b42.jpg")

def datauri(p):
    return "data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode()

CSS = """/* ============================================================
   Uplink host layer — B42 re-skin (Songbird)
   Overrides the uplink theme's variables + wallpaper. Loaded by
   uplink-pve-theme as the per-host layer after uplink.css.
   ============================================================ */

:root {
  /* retune uplink's palette to the B42 black / white / iridescent */
  --ul-night: #0c0c0c;
  --ul-periwinkle: #68aada;
  --ul-periwinkle-dark: #5bd2e9;
  --ul-lavender: #9fa2da;
  --ul-haze: #5bd2e9;
  --ul-star: #f3a2ad;
  --ul-star-glow: rgba(243, 162, 173, .35);
  --ul-glass: rgba(10, 12, 16, .58);
  --ul-glass-strong: rgba(10, 12, 16, .80);
  --ul-line: rgba(237, 241, 243, .14);
  /* iridescent chart series (read by uplink.js) */
  --ul-series: #5bd2e9, #68aada, #9fa2da, #f3a2ad, #edf1f3, #8a8d90;
}

/* swap uplink's backdrop for the B42 wallpaper, neutral scrim */
body::before {
  background: url("__IMG__") center / cover no-repeat !important;
}
body::after {
  background: linear-gradient(180deg,
    rgba(8, 8, 9, .22) 0%, rgba(8, 8, 9, .40) 60%, rgba(8, 8, 9, .58) 100%) !important;
}
"""

out = os.path.join(HERE, "uplink-host-b42.css")
open(out, "w").write(CSS.replace("__IMG__", datauri(IMG)))
print("uplink-host-b42.css", f"{os.path.getsize(out)/1024:.0f} KiB")
