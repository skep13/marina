#!/usr/bin/env python3
"""Generate lib/client.js (the DSH browser bundle) for the Forge theme.
Run after editing the palette or CSS here:  python3 build.py
Forge is dark-only: DSH's light mode is overridden too."""
import json, pathlib
HERE = pathlib.Path(__file__).parent

def hx(c): c = c.lstrip('#'); return [int(c[i:i+2], 16) for i in (0, 2, 4)]
def mix(a, b, t): return '#' + ''.join(f'{round(x+(y-x)*t):02x}' for x, y in zip(hx(a), hx(b)))

# DSH lightness index (0 = lightest .. 1000 = darkest) -> forge iron/ash/bone
ANCHORS = [(0, '#fbf7f1'), (50, '#f1e9dc'), (100, '#e6dccd'), (200, '#d8ccba'), (300, '#c4b6a2'),
           (400, '#a69784'), (600, '#8f8577'), (700, '#6b6155'), (750, '#463c33'), (800, '#342c25'),
           (850, '#251f1a'), (875, '#1c1713'), (900, '#15110e'), (950, '#0c0a08'), (1000, '#070605')]
def ramp(i):
    for (a, ca), (b, cb) in zip(ANCHORS, ANCHORS[1:]):
        if a <= i <= b: return mix(ca, cb, (i - a) / (b - a))

EMBER = {50: '#fff4ec', 100: '#ffe8d6', 200: '#ffd3b0', 300: '#ffb780', 400: '#ff9a55', 450: '#ff8a40',
         500: '#ff7a2f', 600: '#d9531a', 800: '#7a2c0e', 900: '#3d1a0b'}
STEEL = {50: '#f1f3f5', 75: '#e8ecef', 100: '#dfe4e8', 300: '#b4bdc6', 400: '#97a2ad', 450: '#8794a0',
         500: '#7b8794', 600: '#5d6875', 800: '#3d4651', 900: '#2a3038', 950: '#1d2127'}

def name(scale, s): return f'--dsw-static-{scale}-{s:02d}' if s == 0 else f'--dsw-static-{scale}-{s}'
t = {}
for s in [0, 50, 55, 60, 75, 90, 100, 150, 200, 300, 310, 400, 500, 600, 700, 750, 800, 850, 875, 900, 950, 1000]:
    t[name('neutral-bluish', s)] = ramp(s)
for s in [0, 50, 100, 150, 200, 250, 300, 400, 500, 550, 600, 700, 800, 850, 900, 1000]:
    t[name('neutral', s)] = ramp(s)
for s, v in EMBER.items(): t[f'--dsw-static-deepseek-{s}'] = v
for s, v in STEEL.items(): t[f'--dsw-static-blue-{s}'] = v
t.update({   # dark-mode alias tweaks
    '--dsw-alias-bg-base': '#0c0a08',
    '--dsw-alias-bg-layer-1': '#15110e',
    '--dsw-alias-bg-layer-2': '#1c1713',
    '--dsw-alias-bg-layer-3': '#251f1a',
    '--dsw-alias-brand-primary': '#ff7a2f',
    '--dsw-alias-brand-primary-invert': '#0c0a08',
    '--dsw-alias-button-primary-fill': '#ff7a2f',
    '--dsw-alias-button-primary-hover': '#ffb257',
    '--dsw-alias-label-primary-foreground': '#0c0a08',
    '--dsw-alias-brand-primary-new-colorprimary-new-color': '#ff7a2f',
    '--dsw-alias-link': '#ffb257',
    '--dsw-alias-interactive-bg-hover': '#ff7a2f14',
    '--dsw-alias-interactive-bg-active': '#ff7a2f24',
    '--dsw-alias-interactive-bg-hover-accent': '#ff7a2f3d',
    '--dsw-alias-bg-document-selection': '#ff7a2f59',
    '--dsw-alias-label-deep-diving': '#ffb257',
    '--dsw-alias-label-deep-diving-shimmer': '#ffe0a8',
    '--dsw-alias-markdown-inline-code': '#251f1a',
    '--dsw-alias-markdown-code-block': '#110e0b',
    '--dsw-alias-markdown-code-block-banner': '#1c1713',
    '--dsw-alias-border-l1': '#ffb2570f',
    '--dsw-alias-border-l2': '#ffb2571c',
    '--dsw-alias-border-l3': '#ffb25726',
    '--dsw-alias-border-l4': '#ffb25733',
    '--dsw-alias-scrollbar-bg-l1': '#3d342b',
    '--dsw-alias-scrollbar-bg-l2': '#3d342b',
    '--dsw-alias-scrollbar-hover-l1': '#7a2c0e',
    '--dsw-alias-scrollbar-hover-l2': '#7a2c0e',
    '--dsw-alias-bg-mask-drop': '#0c0a08b3',
    '--dsw-font-family': '"Avenir Next", "Helvetica Neue", -apple-system, sans-serif',
    '--ds-font-family-code': '"SF Mono", ui-monospace, Menlo, monospace',
})
TOKENS = {k: {'light': v, 'dark': v} for k, v in t.items()}

GRAIN = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
         "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/></filter>"
         "<rect width='100%' height='100%' filter='url(%23n)'/></svg>")
CSS = r"""
/* ============ FORGE — a blacksmith's shop, not a chat app ============ */
:root {
  --f-iron: #0c0a08; --f-iron-2: #15110e; --f-iron-3: #1c1713; --f-seam: #2a221b;
  --f-bone: #f1e9dc; --f-ash: #8f8577; --f-ember: #ff7a2f; --f-hot: #ffb257; --f-deep: #c2410c;
  --f-gold: #e3b450; --f-steel: #7b8794; --f-steel-hi: #a9b3bd;
  --f-display: "Avenir Next Condensed", "Avenir Next", "Helvetica Neue", sans-serif;
  --f-mono: "SF Mono", ui-monospace, Menlo, monospace;
  --f-heat: 1;
}
html, body { background: var(--f-iron); color-scheme: dark; }
::selection { background: rgba(255,122,47,.38); color: #fff4ec; }

/* ---- the hearth: glow + grain + sparks, all click-through ---- */
body::before {
  content: ""; position: fixed; left: -10vw; right: -10vw; bottom: -6vh; height: 62vh; pointer-events: none; z-index: 2147482000;
  background:
    radial-gradient(ellipse 45% 70% at 58% 100%, rgba(255,150,60,.16), transparent 70%),
    radial-gradient(ellipse 80% 100% at 50% 100%, rgba(255,90,25,.12) 0%, rgba(194,65,12,.05) 45%, transparent 75%);
  mix-blend-mode: screen; transform-origin: 50% 100%;
  animation: f-breathe 7s ease-in-out infinite;
}
body::after {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 2147482001;
  background-image: url("GRAIN"); opacity: .05; mix-blend-mode: overlay;
}
@keyframes f-breathe { 0%,100% { opacity: .7; transform: scaleY(.96) } 50% { opacity: 1; transform: scaleY(1.04) } }
/* bellows: while Forge is working the fire roars */
body:has(button[aria-label="Stop generating"])::before { animation-duration: 1.6s; filter: brightness(1.5) hue-rotate(-8deg); }

#forge-sparks { position: fixed; inset: 0; pointer-events: none; z-index: 2147482002; overflow: hidden; mix-blend-mode: screen; }
#forge-sparks i {
  position: absolute; bottom: -12px; width: 3px; height: 3px; border-radius: 50%;
  background: radial-gradient(circle, #fff3d1 0%, #ffb257 45%, rgba(255,122,47,0) 75%);
  box-shadow: 0 0 6px 1px rgba(255,140,50,.8);
  opacity: 0; animation: f-spark linear infinite;
}
@keyframes f-spark {
  0%   { opacity: 0; transform: translate(0,0) scale(1); }
  8%   { opacity: 1; }
  70%  { opacity: .7; }
  100% { opacity: 0; transform: translate(var(--dx), -82vh) scale(.3); }
}
#forge-sparks i.f-busy { display: none; }
body:has(button[aria-label="Stop generating"]) #forge-sparks i.f-busy { display: block; }
@media (prefers-reduced-motion: reduce) { body::before { animation: none } #forge-sparks { display: none } }

/* ---- the shop wall: brushed dark iron sidebar with a steel seam ---- */
[class*="_sidebarCol"] {
  background:
    repeating-linear-gradient(90deg, rgba(255,255,255,.012) 0 1px, transparent 1px 3px),
    linear-gradient(180deg, #100d0b 0%, #0a0807 100%) !important;
  box-shadow: inset -1px 0 0 var(--f-seam), inset -2px 0 0 rgba(0,0,0,.6);
}
/* stamped section labels */
[class*="_sectionLabel"] {
  font: 600 10.5px/1 var(--f-mono) !important; letter-spacing: .18em; text-transform: uppercase; color: var(--f-ash) !important;
}
/* New Session: a forged iron plate with a hot edge */
button[class*="_newSession"] {
  background: linear-gradient(180deg, #2a221b, #1a1511) !important;
  border: 1px solid #3a2f25 !important; border-radius: 6px !important;
  box-shadow: inset 0 1px 0 rgba(255,220,180,.07), inset 0 -2px 0 rgba(255,122,47,.35), 0 2px 0 #050403 !important;
  font: 700 13px/1 var(--f-display) !important; letter-spacing: .12em; text-transform: uppercase; color: var(--f-bone) !important;
  transition: box-shadow .25s, transform .1s;
}
button[class*="_newSession"]:hover { box-shadow: inset 0 1px 0 rgba(255,220,180,.1), inset 0 -2px 0 var(--f-hot), 0 0 18px -4px rgba(255,122,47,.6), 0 2px 0 #050403 !important; }
button[class*="_newSession"]:active { transform: translateY(1px); }
/* session rows: the selected one is a bar pulled from the fire */
[class*="_sessionRow"] { border-radius: 4px !important; position: relative; transition: background .2s; }
[class*="_sessionRow"][class*="_selected"] {
  background: linear-gradient(90deg, rgba(255,122,47,.22), rgba(255,122,47,.04) 70%, transparent) !important;
  box-shadow: inset 2px 0 0 var(--f-ember), -6px 0 14px -6px rgba(255,122,47,.9);
}
[class*="_sessionRow"][class*="_selected"] [class*="_title"] { color: #fff4ec !important; }
[class*="_projectRow"] [class*="_title"] { font-weight: 600; }

/* ---- the start screen ---- */
[class*="_titleGroup"] > span:first-child {
  font: 700 46px/1.05 var(--f-display) !important; letter-spacing: -.005em; text-transform: none;
  background: linear-gradient(180deg, #f6efe4 22%, var(--f-hot) 64%, var(--f-ember) 82%, var(--f-deep) 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent !important;
  padding: .14em .02em .02em; filter: drop-shadow(0 0 22px rgba(255,105,35,.28));
}
[class*="_previewBadge"] { display: none !important; }
[class*="_headline"] { animation: f-rise .9s cubic-bezier(.2,.7,.1,1) both; }
[class*="_root"][class*="_hero"] > [class*="_card"] { animation: f-rise .9s .15s cubic-bezier(.2,.7,.1,1) both; }
@keyframes f-rise { from { opacity: 0; transform: translateY(14px); filter: blur(3px) } to { opacity: 1; transform: none; filter: none } }

/* ---- the anvil: riveted steel plate that heats up when you work it ---- */
[class*="_root"] > [class*="_card"] {
  background:
    radial-gradient(circle at 10px 10px, #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),
    radial-gradient(circle at calc(100% - 10px) 10px, #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),
    radial-gradient(circle at 10px calc(100% - 10px), #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),
    radial-gradient(circle at calc(100% - 10px) calc(100% - 10px), #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),
    linear-gradient(180deg, #1d1814 0%, #141009 100%) !important;
  border: 1px solid #3a2f25 !important; border-radius: 10px !important;
  box-shadow: inset 0 1px 0 rgba(255,220,180,.06), 0 0 0 1px #050403, 0 20px 50px -22px rgba(255,105,35,.45) !important;
  transition: box-shadow .4s, border-color .4s;
}
[class*="_root"] > [class*="_card"]:focus-within {
  border-color: rgba(255,154,85,.55) !important;
  box-shadow: inset 0 1px 0 rgba(255,220,180,.08), inset 0 -3px 0 -1px rgba(255,122,47,.6), 0 0 0 1px rgba(255,122,47,.25),
              0 0 34px -6px rgba(255,105,35,.55), 0 24px 60px -18px rgba(255,105,35,.6) !important;
}
body:has(button[aria-label="Stop generating"]) [class*="_root"] > [class*="_card"] { animation: f-glow 1.6s ease-in-out infinite; }
@keyframes f-glow { 50% { border-color: rgba(255,178,87,.7); box-shadow: 0 0 0 1px rgba(255,122,47,.35), 0 0 40px -4px rgba(255,105,35,.7) } }

/* send: a molten drop */
button[aria-label="Send message"] {
  background: radial-gradient(circle at 50% 30%, #fff1d6 0%, #ffb257 28%, #ff7a2f 60%, #c2410c 100%) !important;
  box-shadow: 0 0 16px rgba(255,122,47,.65), inset 0 -2px 3px rgba(120,30,0,.5) !important;
  color: #1a0d05 !important; transition: transform .15s, box-shadow .2s;
}
button[aria-label="Send message"]:not(:disabled):hover { transform: scale(1.08); box-shadow: 0 0 26px 4px rgba(255,140,50,.8) !important; }
button[aria-label="Send message"]:disabled { filter: grayscale(.55) brightness(.6); box-shadow: inset 0 -2px 3px rgba(0,0,0,.5) !important; }
button[aria-label="Stop generating"] {
  background: linear-gradient(180deg, #a9b3bd, #5d6875) !important; color: #0c0a08 !important;
  box-shadow: 0 0 0 2px rgba(255,122,47,.5), 0 0 18px rgba(255,122,47,.6) !important;
}

/* stamped readouts (tok/s, tokens, context) */
[class*="_pill"] { font-family: var(--f-mono) !important; letter-spacing: .06em; color: var(--f-gold) !important; }

/* ---- the conversation ---- */
/* your messages: a struck steel plate */
[class*="_userStack"] [class*="_bubble"] {
  background: linear-gradient(180deg, #2a2520 0%, #1f1a16 100%) !important;
  border: 1px solid #3a2f25; border-radius: 10px 10px 2px 10px !important;
  box-shadow: inset 0 1px 0 rgba(255,220,180,.07), 0 6px 18px -10px #000;
}
/* headings in the answer: hammered type */
[class*="_markdown"] h1, [class*="_markdown"] h2, [class*="_markdown"] h3 {
  font-family: var(--f-display) !important; text-transform: uppercase; letter-spacing: .03em; color: var(--f-bone);
}
[class*="_markdown"] h1, [class*="_markdown"] h2 { border-bottom: 1px solid var(--f-seam); padding-bottom: .25em; }
[class*="_markdown"] strong { color: #fff4ec; }
[class*="_markdown"] li::marker { color: var(--f-ember); }
[class*="_markdown"] a { color: var(--f-hot) !important; text-decoration-color: rgba(255,178,87,.4); }
[class*="_markdown"] blockquote { border-left: 2px solid var(--f-steel) !important; color: var(--f-steel-hi); }
/* code: blackened steel with an ember edge */
pre { border-left: 2px solid rgba(255,122,47,.6) !important; background: #0e0b09 !important; box-shadow: inset 0 0 0 1px #2a221b; }
code { font-family: var(--f-mono) !important; }
[class*="_markdown"] :not(pre) > code { color: var(--f-hot); background: #241d17 !important; border: 1px solid #33291f; }
/* view tabs (Chat / Trajectory): stamped */
[class*="_tabLabel"] { font: 600 11px/1 var(--f-mono) !important; letter-spacing: .14em; text-transform: uppercase; }
/* file cards: a tag on the workbench */
[class*="_fileLink"] { border-color: #3a2f25 !important; }

/* scrollbars: cold iron, glowing on touch */
* { scrollbar-color: #3a2f25 transparent; }
*::-webkit-scrollbar-thumb { background: #3a2f25; border-radius: 6px; }
*::-webkit-scrollbar-thumb:hover { background: var(--f-deep); }
""".replace("GRAIN", GRAIN)

client = HERE / 'lib' / 'client.js'
src = (HERE / 'client.template.js').read_text()
src = src.replace('/*TOKENS*/', json.dumps(TOKENS, indent='\t')).replace('/*CSS*/', json.dumps(CSS))
client.write_text(src)
(HERE / 'lib' / 'tokens.json').write_text(json.dumps(TOKENS, indent=1))
print(f'wrote {client} ({len(TOKENS)} tokens, {len(CSS)} bytes css)')
