#!/usr/bin/env python3
"""Generate proxmox-b42.css: a brutalist black/white + iridescent dark theme
for the Proxmox VE web UI (ExtJS), with the B42 wallpaper embedded.
Applied to all three labs (lab1/lab2/lab3)."""
import base64, os

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "assets", "proxmox-b42.jpg")

def datauri(p):
    return "data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode()

CSS = """/* ============================================================
   Proxmox VE — "B42" brutalist dark theme
   ------------------------------------------------------------
   Black/white brutalist wallpaper with an iridescent accent
   (cyan -> blue -> periwinkle -> pink), palette sampled from the
   image. Dark ExtJS chrome so the dense PVE tables stay legible;
   the wallpaper shows on the login screen and behind the header.

   Same file for lab1, lab2 and lab3. Inject by linking it from
   /usr/share/pve-manager/index.html.tpl (see the apply notes).
   ============================================================ */

:root {
  --px-black:   #0c0c0c;
  --px-panel:   #141416;   /* panels / grids */
  --px-panel2:  #1c1c1f;   /* toolbars / headers */
  --px-bezel:   #2b2b30;   /* hairlines */
  --px-white:   #edf1f3;
  --px-ink:     #d7dbdd;
  --px-ink-dim: #8a8d90;
  /* the iridescent strip */
  --px-cyan:    #5bd2e9;
  --px-blue:    #68aada;
  --px-peri:    #9fa2da;
  --px-pink:    #f3a2ad;
  --px-iris: linear-gradient(90deg,
     var(--px-cyan) 0%, var(--px-blue) 34%, var(--px-peri) 67%, var(--px-pink) 100%);
  --px-accent:  var(--px-blue);
  --px-font: "DepartureMono","IBM Plex Mono","JetBrains Mono",
             ui-monospace,Menlo,monospace;
}

/* ---- wallpaper + scrim ---------------------------------------- */
/* PVE paints the whole screen with .x-viewport>.x-body (#1a1a1a) and
   .x-border-layout-ct, so the wallpaper goes on THOSE (the real base
   layers), not just <body>, or it is covered. */
html, body { background-color: var(--px-black) !important;
  color: var(--px-ink) !important; font-family: var(--px-font) !important; }

.x-viewport > .x-body, .x-body {
  background-color: var(--px-black) !important;
  background-image:
    linear-gradient(180deg, rgba(8,8,9,.42) 0%, rgba(8,8,9,.52) 55%, rgba(8,8,9,.66) 100%),
    url("__IMG__") !important;
  background-size: auto, cover !important;
  background-position: center, center !important;
  background-repeat: no-repeat, no-repeat !important;
  background-attachment: fixed, fixed !important;
}
/* the layout container and login window sit transparent over the wallpaper */
body.x-border-layout-ct, div.x-border-layout-ct,
.pve-login-window, .pve-login-window .x-window-body-default,
.x-mask { background-color: transparent !important; }

/* ---- panel bodies: transparent so the wallpaper reads through -- */
.x-panel-body-default, .x-panel-body, .x-autocontainer-body,
.x-container-default, .x-box-inner, .x-autocontainer-innerCt,
.x-tab-panel-default, .x-grid-view, .x-tree-view, .x-grid-empty,
.x-panel-default { background-color: transparent !important; }

/* ---- surfaces that hold text get a translucent dark backing ---- */
.x-grid-item, .x-column-header-default, .x-grid-cell-row-numberer,
.x-grid-group-hd, .x-treelist-item, .x-treelist-pve-nav {
  background-color: color-mix(in srgb, var(--px-panel) 58%, transparent) !important;
  color: var(--px-ink) !important; border-color: var(--px-bezel) !important;
}
.x-grid-item-alt { background-color: color-mix(in srgb, var(--px-black) 52%, transparent) !important; }
.x-toolbar, .x-toolbar-default, .x-tab-bar-default, .x-grid-header-ct,
.x-menu-body-default, .x-window-body-default, .x-window-header,
.x-panel-header, .x-panel-header-default {
  background-color: color-mix(in srgb, var(--px-panel2) 74%, transparent) !important;
  color: var(--px-white) !important; border-color: var(--px-bezel) !important;
  backdrop-filter: blur(5px);
}
.x-panel-header-title, .x-column-header-text, .x-window-header-title,
.x-panel-header-title-default { color: var(--px-white) !important; letter-spacing: .04em; }

/* the top PVE header bar gets the iridescent underline */
#pveloginbar, .x-docked-top.x-toolbar, .pve-toolbar-top {
  border-bottom: 2px solid transparent !important;
  border-image: var(--px-iris) 1 !important;
}

/* recolor the theme's blue selection to our cyan, hover to translucent */
.x-treelist-item-selected > .x-treelist-row,
.x-grid-item-selected, .x-grid-row-selected {
  background-color: color-mix(in srgb, var(--px-blue) 34%, transparent) !important;
  box-shadow: inset 2px 0 0 var(--px-cyan); color: var(--px-white) !important;
}
.x-grid-item-over, .x-treelist-row-over {
  background-color: color-mix(in srgb, var(--px-cyan) 16%, transparent) !important;
}

/* the top PVE header bar gets the iridescent underline */
#pveloginbar, .x-docked-top.x-toolbar, .pve-toolbar-top {
  border-bottom: 2px solid transparent !important;
  border-image: var(--px-iris) 1 !important;
}

/* ---- grid cell text ------------------------------------------- */
.x-grid-cell, .x-grid-cell-inner, .x-tree-node-text { color: var(--px-ink) !important; }

/* ---- tabs ----------------------------------------------------- */
.x-tab { background: var(--px-panel2) !important; color: var(--px-ink-dim) !important;
  border-color: var(--px-bezel) !important; }
.x-tab-active { color: var(--px-white) !important;
  border-bottom: 2px solid transparent !important;
  border-image: var(--px-iris) 1 !important; }
.x-tab-over { color: var(--px-cyan) !important; }

/* ---- buttons -------------------------------------------------- */
.x-btn, .x-btn-default-small, .x-btn-default-toolbar-small {
  background: var(--px-panel2) !important;
  border: 1px solid var(--px-bezel) !important;
  color: var(--px-ink) !important;
}
.x-btn-over { border-color: var(--px-cyan) !important; color: var(--px-white) !important;
  box-shadow: 0 0 10px rgba(91,210,233,.35); }
.x-btn-pressed, .x-btn-menu-active {
  background: color-mix(in srgb, var(--px-blue) 24%, var(--px-panel2)) !important; }
/* primary action buttons carry the iridescent fill */
.x-btn.x-btn-default-small.pve-primary, .pve-login-window .x-btn {
  background: var(--px-iris) !important; color: #0a0a0c !important;
  border: none !important; font-weight: 700;
}

/* ---- inputs --------------------------------------------------- */
.x-form-text, .x-form-field, .x-form-textarea, input, select, textarea {
  background: var(--px-black) !important;
  color: var(--px-white) !important;
  border: 1px solid var(--px-bezel) !important;
}
.x-form-focus, .x-field-focus, input:focus, textarea:focus {
  border-color: var(--px-cyan) !important;
  box-shadow: 0 0 0 1px var(--px-cyan), 0 0 12px rgba(91,210,233,.35) !important;
}

/* ---- windows / modals ----------------------------------------- */
.x-window, .x-window-body { background: var(--px-panel) !important;
  border: 1px solid var(--px-bezel) !important; }
.x-window-header { border-bottom: 2px solid transparent !important;
  border-image: var(--px-iris) 1 !important; }
.x-mask { background: rgba(6,6,7,.72) !important; }

/* ---- the "Virtual Environment" logo text ---------------------- */
.x-unselectable.x-box-item .pve-online, .x-toolbar .x-title-text {
  color: var(--px-white) !important; letter-spacing: .12em; text-transform: uppercase;
}

/* ---- status: running green / stopped etc. keep readable ------- */
.x-grid-cell .good, .pmx-tree-status-good { color: var(--px-cyan) !important; }
.critical, .x-grid-cell .critical { color: var(--px-pink) !important; }

/* ---- scrollbars as iridescent tracks -------------------------- */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--px-black); }
::-webkit-scrollbar-thumb { background: var(--px-iris); border: 1px solid var(--px-bezel); }

::selection { background: var(--px-cyan); color: #0a0a0c; }
a, .x-tool-tool-el { color: var(--px-cyan) !important; }
.x-splitter { background: var(--px-bezel) !important; }
"""

out = os.path.join(HERE, "proxmox-b42.css")
open(out, "w").write(CSS.replace("__IMG__", datauri(IMG)))
print("proxmox-b42.css", f"{os.path.getsize(out)/1024:.0f} KiB")
