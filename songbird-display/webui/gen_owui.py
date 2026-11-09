import base64, os
A=os.path.join(os.path.dirname(os.path.abspath(__file__)),"assets")+"/"

def datauri(path):
    b = base64.b64encode(open(path,'rb').read()).decode()
    return f"data:image/jpeg;base64,{b}"

TEMPLATE = """/* ============================================================
   {title}
   ------------------------------------------------------------
   Retro-futurist theme for {where}, built from the reference
   art the owner chose. The portrait is anchored to the right and
   scaled to cover; a scrim over the content side keeps text
   legible. Palette sampled straight from the image.

   Single self-contained file (background embedded) — paste into
   Open WebUI's custom CSS, or <link>/inject into any dashboard.
   ============================================================ */

:root {{
  --bg:      {bg};
  --panel:   {panel};
  --panel2:  {panel2};
  --bezel:   {bezel};
  --c1:      {c1};      /* primary  */
  --c1-dim:  {c1dim};
  --c1-glow: {c1glow};
  --c2:      {c2};      /* secondary (user) */
  --c2-glow: {c2glow};
  --c3:      {c3};      /* highlight (assistant phosphor) */
  --c3-glow: {c3glow};
  --ink:     {ink};
  --ink-dim: {inkdim};
  --mono: "DepartureMono","IBM Plex Mono","JetBrains Mono",ui-monospace,Menlo,monospace;

  /* Open WebUI is Tailwind v4: bg-gray-* => var(--color-gray-*). Make the
     surface grays TRANSLUCENT so the app chrome stops covering the wallpaper. */
  --color-gray-50:#f3edf2;--color-gray-100:{ink};--color-gray-200:#cbbfd6;
  --color-gray-300:#a89bbd;--color-gray-400:{inkdim};--color-gray-500:#5c5570;
  --color-gray-600:{bezel};
  --color-gray-700:color-mix(in srgb, {panel2} 82%, transparent);
  --color-gray-800:color-mix(in srgb, {panel} 72%, transparent);
  --color-gray-850:color-mix(in srgb, {bg} 62%, transparent);
  --color-gray-900:color-mix(in srgb, {bg} 56%, transparent);
  --color-gray-950:color-mix(in srgb, {bg} 74%, transparent);
}}

/* ---- full-page art backdrop + scrim ---------------------- */
/* Wallpaper + scrim + scanlines go on <html> (the base layer, fixed to
   the viewport), and <body> plus the app shell are made transparent, so
   Open WebUI's own opaque surfaces never paint over the art. */
html {{
  background-image:
    repeating-linear-gradient(to bottom, transparent 0 2px, rgba(0,0,0,.22) 3px),
    linear-gradient(180deg, {scrimTop} 0%, {scrimMid} 52%, {scrimBot} 100%),
    url("{img}") !important;
  background-size: auto, auto, cover !important;
  background-position: center, center, {imgpos} !important;
  background-repeat: repeat, no-repeat, no-repeat !important;
  background-attachment: fixed, fixed, fixed !important;
  background-color: var(--bg) !important;
}}
html, body, body.dark {{
  color: var(--ink) !important;
  font-family: var(--mono) !important;
  text-shadow: 0 1px 3px rgba(0,0,0,.6);
  min-height: 100vh;
}}
body, body.dark {{ background: transparent !important; }}
/* let the art show through the app shell + its full-height containers */
#app, #messages-container, .main, .chat-container, [class*="chat"],
.h-screen, .min-h-screen, .h-full, .w-full.h-full {{
  background-color: transparent !important;
}}

/* ---- top strip ------------------------------------------- */
nav, header, .sticky.top-0, [class*="navbar"] {{
  background: linear-gradient(180deg, {panel} 0%, transparent 100%) !important;
  border-bottom: 1px solid var(--c1-dim) !important; backdrop-filter: blur(2px);
}}
nav .font-primary, nav .text-lg, .font-primary {{
  color: var(--c1) !important; text-shadow: 0 0 8px var(--c1-glow);
  letter-spacing:.14em; text-transform:uppercase;
}}

/* ---- sidebar --------------------------------------------- */
#sidebar, nav#sidebar, [class*="sidebar"] {{
  background: color-mix(in srgb, var(--panel) 86%, transparent) !important;
  border-right: 1px solid var(--bezel) !important; backdrop-filter: blur(3px);
}}
#sidebar a, #sidebar button {{ color: var(--ink-dim) !important; border-radius:2px !important; }}
#sidebar a:hover, #sidebar button:hover, #sidebar a.selected, #sidebar .bg-gray-900 {{
  color: var(--c3) !important; background: color-mix(in srgb, var(--c1) 12%, transparent) !important;
  box-shadow: inset 2px 0 0 var(--c1);
}}

/* ---- chat stream ----------------------------------------- */
.chat-container, #messages-container, [class*="chat"] {{ background: transparent !important; }}
[class*="assistant"] .markdown-prose, .chat-assistant, .message .prose {{
  color: var(--c3) !important; text-shadow: 0 0 3px var(--c3-glow);
}}
.chat-user, [class*="user-message"] {{
  background: color-mix(in srgb, var(--panel2) 90%, transparent) !important;
  border: 1px solid var(--c2) !important; border-radius:3px !important;
  color: var(--c2) !important; backdrop-filter: blur(2px);
}}
pre, code, .hljs {{
  background: color-mix(in srgb, var(--bg) 90%, transparent) !important;
  border: 1px solid var(--bezel) !important; color: var(--c3) !important; border-radius:2px !important;
}}

/* ---- composer / inputs ----------------------------------- */
#chat-input, textarea, input[type=text], input[type=search], .bg-gray-50, .dark\\:bg-gray-800 {{
  background: color-mix(in srgb, var(--panel2) 92%, transparent) !important;
  color: var(--ink) !important; border:1px solid var(--bezel) !important;
  border-radius:3px !important; font-family: var(--mono) !important; backdrop-filter: blur(3px);
}}
#chat-input:focus, textarea:focus, input:focus {{
  border-color: var(--c1) !important;
  box-shadow: 0 0 0 1px var(--c1), 0 0 14px var(--c1-glow) !important; outline:none !important;
}}
::placeholder {{ color: var(--ink-dim) !important; }}
button[type=submit], [class*="send"] {{
  background: var(--c1) !important; color: #fff !important; border-radius:3px !important;
  box-shadow: 0 0 12px var(--c1-glow);
}}
button[type=submit]:hover {{ filter: brightness(1.15); }}
button, .rounded-xl, .rounded-lg {{ border-radius:3px !important; }}
button:not([type=submit]):hover {{ color: var(--c3) !important; }}

/* ---- scrollbars as LED tracks ---------------------------- */
*::-webkit-scrollbar {{ width:10px; height:10px; }}
*::-webkit-scrollbar-track {{ background: transparent; }}
*::-webkit-scrollbar-thumb {{
  background: repeating-linear-gradient(to bottom, var(--c1) 0 4px, transparent 4px 6px);
  border:1px solid var(--bezel);
}}

/* ---- Googie starburst at the corner ---------------------- */
#app > nav::before, header::before {{
  content:""; position:absolute; left:14px; top:50%; width:14px; height:14px;
  transform: translateY(-50%);
  background:
    linear-gradient(var(--c1),var(--c1)) 50% 0/2px 100% no-repeat,
    linear-gradient(var(--c1),var(--c1)) 0 50%/100% 2px no-repeat,
    radial-gradient(var(--c1) 2px, transparent 2.5px) 50% 50%/100% 100% no-repeat;
  filter: drop-shadow(0 0 4px var(--c1-glow)); opacity:.9;
}}

::selection {{ background: var(--c2); color:#120c12; }}
a {{ color: var(--c3) !important; }}
hr, .border, .border-t, .border-b {{ border-color: var(--bezel) !important; }}
"""

DAISY = dict(
  title="Open WebUI container — daisy/violet theme", where="an Open WebUI container",
  bg="#120f20", panel="#1b1733", panel2="#231c40", bezel="#3a2f63",
  c1="#8a4be0", c1dim="#542797", c1glow="rgba(138,75,224,.55)",
  c2="#e06a9b", c2glow="rgba(224,106,155,.5)",
  c3="#3ad6b2", c3glow="rgba(58,214,178,.5)",
  ink="#f2e8ed", inkdim="#9a8fb0",
  imgpos="center 18%", scrimTop="rgba(18,15,32,.50)", scrimMid="rgba(18,15,32,.64)", scrimBot="rgba(18,15,32,.92)",
)
REZE = dict(
  title="Open WebUI (Songbird) — Reze ink-punk theme", where="the Songbird Open WebUI container",
  bg="#030506", panel="#0b1113", panel2="#111b1d", bezel="#243a3d",
  c1="#ff2e6e", c1dim="#b01c49", c1glow="rgba(255,46,110,.55)",
  c2="#55c2cc", c2glow="rgba(85,194,204,.5)",
  c3="#55c2cc", c3glow="rgba(85,194,204,.5)",
  ink="#f6cfd1", inkdim="#6f9a9e",
  imgpos="center", scrimTop="rgba(3,5,6,.52)", scrimMid="rgba(3,5,6,.66)", scrimBot="rgba(3,5,6,.93)",
)
CRIMSON = dict(
  title="Open WebUI container — steel & crimson theme", where="an Open WebUI container",
  bg="#121116", panel="#1c1b22", panel2="#26242e", bezel="#3a3845",
  c1="#d11a24", c1dim="#8a1218", c1glow="rgba(209,26,36,.55)",
  c2="#9aa6c0", c2glow="rgba(154,166,192,.45)",
  c3="#d6dae2", c3glow="rgba(214,218,226,.4)",
  ink="#e4e6ec", inkdim="#96959d",
  imgpos="center 12%", scrimTop="rgba(18,17,22,.52)", scrimMid="rgba(18,17,22,.66)", scrimBot="rgba(18,17,22,.93)",
)
OUT="/Users/jacobmatthews/marina/songbird-display/webui"
for cfg, img, fname in [(DAISY,A+"owui-daisy.jpg","owui-daisy.css"),(REZE,A+"owui-reze.jpg","owui-reze.css"),(CRIMSON,A+"owui-crimson.jpg","owui-crimson.css")]:
    cfg=dict(cfg); cfg["img"]=datauri(img)
    open(f"{OUT}/{fname}","w").write(TEMPLATE.format(**cfg))
    print(fname)
