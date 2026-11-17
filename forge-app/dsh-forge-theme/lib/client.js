// Generated into lib/client.js by build.py — edit this template or build.py, not lib/client.js.
window.__ModuleLoader__.load({
	id: "dsh-forge-theme",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		const { jsx, jsxs } = require("react/jsx-runtime");

		const TOKENS = {
	"--dsw-static-neutral-bluish-00": {
		"light": "#fbf7f1",
		"dark": "#fbf7f1"
	},
	"--dsw-static-neutral-bluish-50": {
		"light": "#f1e9dc",
		"dark": "#f1e9dc"
	},
	"--dsw-static-neutral-bluish-55": {
		"light": "#f0e8da",
		"dark": "#f0e8da"
	},
	"--dsw-static-neutral-bluish-60": {
		"light": "#efe6d9",
		"dark": "#efe6d9"
	},
	"--dsw-static-neutral-bluish-75": {
		"light": "#ece2d4",
		"dark": "#ece2d4"
	},
	"--dsw-static-neutral-bluish-90": {
		"light": "#e8dfd0",
		"dark": "#e8dfd0"
	},
	"--dsw-static-neutral-bluish-100": {
		"light": "#e6dccd",
		"dark": "#e6dccd"
	},
	"--dsw-static-neutral-bluish-150": {
		"light": "#dfd4c4",
		"dark": "#dfd4c4"
	},
	"--dsw-static-neutral-bluish-200": {
		"light": "#d8ccba",
		"dark": "#d8ccba"
	},
	"--dsw-static-neutral-bluish-300": {
		"light": "#c4b6a2",
		"dark": "#c4b6a2"
	},
	"--dsw-static-neutral-bluish-310": {
		"light": "#c1b39f",
		"dark": "#c1b39f"
	},
	"--dsw-static-neutral-bluish-400": {
		"light": "#a69784",
		"dark": "#a69784"
	},
	"--dsw-static-neutral-bluish-500": {
		"light": "#9a8e7e",
		"dark": "#9a8e7e"
	},
	"--dsw-static-neutral-bluish-600": {
		"light": "#8f8577",
		"dark": "#8f8577"
	},
	"--dsw-static-neutral-bluish-700": {
		"light": "#6b6155",
		"dark": "#6b6155"
	},
	"--dsw-static-neutral-bluish-750": {
		"light": "#463c33",
		"dark": "#463c33"
	},
	"--dsw-static-neutral-bluish-800": {
		"light": "#342c25",
		"dark": "#342c25"
	},
	"--dsw-static-neutral-bluish-850": {
		"light": "#251f1a",
		"dark": "#251f1a"
	},
	"--dsw-static-neutral-bluish-875": {
		"light": "#1c1713",
		"dark": "#1c1713"
	},
	"--dsw-static-neutral-bluish-900": {
		"light": "#15110e",
		"dark": "#15110e"
	},
	"--dsw-static-neutral-bluish-950": {
		"light": "#0c0a08",
		"dark": "#0c0a08"
	},
	"--dsw-static-neutral-bluish-1000": {
		"light": "#070605",
		"dark": "#070605"
	},
	"--dsw-static-neutral-00": {
		"light": "#fbf7f1",
		"dark": "#fbf7f1"
	},
	"--dsw-static-neutral-50": {
		"light": "#f1e9dc",
		"dark": "#f1e9dc"
	},
	"--dsw-static-neutral-100": {
		"light": "#e6dccd",
		"dark": "#e6dccd"
	},
	"--dsw-static-neutral-150": {
		"light": "#dfd4c4",
		"dark": "#dfd4c4"
	},
	"--dsw-static-neutral-200": {
		"light": "#d8ccba",
		"dark": "#d8ccba"
	},
	"--dsw-static-neutral-250": {
		"light": "#cec1ae",
		"dark": "#cec1ae"
	},
	"--dsw-static-neutral-300": {
		"light": "#c4b6a2",
		"dark": "#c4b6a2"
	},
	"--dsw-static-neutral-400": {
		"light": "#a69784",
		"dark": "#a69784"
	},
	"--dsw-static-neutral-500": {
		"light": "#9a8e7e",
		"dark": "#9a8e7e"
	},
	"--dsw-static-neutral-550": {
		"light": "#958a7a",
		"dark": "#958a7a"
	},
	"--dsw-static-neutral-600": {
		"light": "#8f8577",
		"dark": "#8f8577"
	},
	"--dsw-static-neutral-700": {
		"light": "#6b6155",
		"dark": "#6b6155"
	},
	"--dsw-static-neutral-800": {
		"light": "#342c25",
		"dark": "#342c25"
	},
	"--dsw-static-neutral-850": {
		"light": "#251f1a",
		"dark": "#251f1a"
	},
	"--dsw-static-neutral-900": {
		"light": "#15110e",
		"dark": "#15110e"
	},
	"--dsw-static-neutral-1000": {
		"light": "#070605",
		"dark": "#070605"
	},
	"--dsw-static-deepseek-50": {
		"light": "#fff4ec",
		"dark": "#fff4ec"
	},
	"--dsw-static-deepseek-100": {
		"light": "#ffe8d6",
		"dark": "#ffe8d6"
	},
	"--dsw-static-deepseek-200": {
		"light": "#ffd3b0",
		"dark": "#ffd3b0"
	},
	"--dsw-static-deepseek-300": {
		"light": "#ffb780",
		"dark": "#ffb780"
	},
	"--dsw-static-deepseek-400": {
		"light": "#ff9a55",
		"dark": "#ff9a55"
	},
	"--dsw-static-deepseek-450": {
		"light": "#ff8a40",
		"dark": "#ff8a40"
	},
	"--dsw-static-deepseek-500": {
		"light": "#ff7a2f",
		"dark": "#ff7a2f"
	},
	"--dsw-static-deepseek-600": {
		"light": "#d9531a",
		"dark": "#d9531a"
	},
	"--dsw-static-deepseek-800": {
		"light": "#7a2c0e",
		"dark": "#7a2c0e"
	},
	"--dsw-static-deepseek-900": {
		"light": "#3d1a0b",
		"dark": "#3d1a0b"
	},
	"--dsw-static-blue-50": {
		"light": "#f1f3f5",
		"dark": "#f1f3f5"
	},
	"--dsw-static-blue-75": {
		"light": "#e8ecef",
		"dark": "#e8ecef"
	},
	"--dsw-static-blue-100": {
		"light": "#dfe4e8",
		"dark": "#dfe4e8"
	},
	"--dsw-static-blue-300": {
		"light": "#b4bdc6",
		"dark": "#b4bdc6"
	},
	"--dsw-static-blue-400": {
		"light": "#97a2ad",
		"dark": "#97a2ad"
	},
	"--dsw-static-blue-450": {
		"light": "#8794a0",
		"dark": "#8794a0"
	},
	"--dsw-static-blue-500": {
		"light": "#7b8794",
		"dark": "#7b8794"
	},
	"--dsw-static-blue-600": {
		"light": "#5d6875",
		"dark": "#5d6875"
	},
	"--dsw-static-blue-800": {
		"light": "#3d4651",
		"dark": "#3d4651"
	},
	"--dsw-static-blue-900": {
		"light": "#2a3038",
		"dark": "#2a3038"
	},
	"--dsw-static-blue-950": {
		"light": "#1d2127",
		"dark": "#1d2127"
	},
	"--dsw-alias-bg-base": {
		"light": "#0c0a08",
		"dark": "#0c0a08"
	},
	"--dsw-alias-bg-layer-1": {
		"light": "#15110e",
		"dark": "#15110e"
	},
	"--dsw-alias-bg-layer-2": {
		"light": "#1c1713",
		"dark": "#1c1713"
	},
	"--dsw-alias-bg-layer-3": {
		"light": "#251f1a",
		"dark": "#251f1a"
	},
	"--dsw-alias-brand-primary": {
		"light": "#ff7a2f",
		"dark": "#ff7a2f"
	},
	"--dsw-alias-brand-primary-invert": {
		"light": "#0c0a08",
		"dark": "#0c0a08"
	},
	"--dsw-alias-button-primary-fill": {
		"light": "#ff7a2f",
		"dark": "#ff7a2f"
	},
	"--dsw-alias-button-primary-hover": {
		"light": "#ffb257",
		"dark": "#ffb257"
	},
	"--dsw-alias-label-primary-foreground": {
		"light": "#0c0a08",
		"dark": "#0c0a08"
	},
	"--dsw-alias-brand-primary-new-colorprimary-new-color": {
		"light": "#ff7a2f",
		"dark": "#ff7a2f"
	},
	"--dsw-alias-link": {
		"light": "#ffb257",
		"dark": "#ffb257"
	},
	"--dsw-alias-interactive-bg-hover": {
		"light": "#ff7a2f14",
		"dark": "#ff7a2f14"
	},
	"--dsw-alias-interactive-bg-active": {
		"light": "#ff7a2f24",
		"dark": "#ff7a2f24"
	},
	"--dsw-alias-interactive-bg-hover-accent": {
		"light": "#ff7a2f3d",
		"dark": "#ff7a2f3d"
	},
	"--dsw-alias-bg-document-selection": {
		"light": "#ff7a2f59",
		"dark": "#ff7a2f59"
	},
	"--dsw-alias-label-deep-diving": {
		"light": "#ffb257",
		"dark": "#ffb257"
	},
	"--dsw-alias-label-deep-diving-shimmer": {
		"light": "#ffe0a8",
		"dark": "#ffe0a8"
	},
	"--dsw-alias-markdown-inline-code": {
		"light": "#251f1a",
		"dark": "#251f1a"
	},
	"--dsw-alias-markdown-code-block": {
		"light": "#110e0b",
		"dark": "#110e0b"
	},
	"--dsw-alias-markdown-code-block-banner": {
		"light": "#1c1713",
		"dark": "#1c1713"
	},
	"--dsw-alias-border-l1": {
		"light": "#ffb2570f",
		"dark": "#ffb2570f"
	},
	"--dsw-alias-border-l2": {
		"light": "#ffb2571c",
		"dark": "#ffb2571c"
	},
	"--dsw-alias-border-l3": {
		"light": "#ffb25726",
		"dark": "#ffb25726"
	},
	"--dsw-alias-border-l4": {
		"light": "#ffb25733",
		"dark": "#ffb25733"
	},
	"--dsw-alias-scrollbar-bg-l1": {
		"light": "#3d342b",
		"dark": "#3d342b"
	},
	"--dsw-alias-scrollbar-bg-l2": {
		"light": "#3d342b",
		"dark": "#3d342b"
	},
	"--dsw-alias-scrollbar-hover-l1": {
		"light": "#7a2c0e",
		"dark": "#7a2c0e"
	},
	"--dsw-alias-scrollbar-hover-l2": {
		"light": "#7a2c0e",
		"dark": "#7a2c0e"
	},
	"--dsw-alias-bg-mask-drop": {
		"light": "#0c0a08b3",
		"dark": "#0c0a08b3"
	},
	"--dsw-font-family": {
		"light": "\"Avenir Next\", \"Helvetica Neue\", -apple-system, sans-serif",
		"dark": "\"Avenir Next\", \"Helvetica Neue\", -apple-system, sans-serif"
	},
	"--ds-font-family-code": {
		"light": "\"SF Mono\", ui-monospace, Menlo, monospace",
		"dark": "\"SF Mono\", ui-monospace, Menlo, monospace"
	}
};
		const CSS = "\n/* ============ FORGE \u2014 a blacksmith's shop, not a chat app ============ */\n:root {\n  --f-iron: #0c0a08; --f-iron-2: #15110e; --f-iron-3: #1c1713; --f-seam: #2a221b;\n  --f-bone: #f1e9dc; --f-ash: #8f8577; --f-ember: #ff7a2f; --f-hot: #ffb257; --f-deep: #c2410c;\n  --f-gold: #e3b450; --f-steel: #7b8794; --f-steel-hi: #a9b3bd;\n  --f-display: \"Avenir Next Condensed\", \"Avenir Next\", \"Helvetica Neue\", sans-serif;\n  --f-mono: \"SF Mono\", ui-monospace, Menlo, monospace;\n  --f-heat: 1;\n}\nhtml, body { background: var(--f-iron); color-scheme: dark; }\n::selection { background: rgba(255,122,47,.38); color: #fff4ec; }\n\n/* ---- the hearth: glow + grain + sparks, all click-through ---- */\nbody::before {\n  content: \"\"; position: fixed; left: -10vw; right: -10vw; bottom: -6vh; height: 62vh; pointer-events: none; z-index: 2147482000;\n  background:\n    radial-gradient(ellipse 45% 70% at 58% 100%, rgba(255,150,60,.16), transparent 70%),\n    radial-gradient(ellipse 80% 100% at 50% 100%, rgba(255,90,25,.12) 0%, rgba(194,65,12,.05) 45%, transparent 75%);\n  mix-blend-mode: screen; transform-origin: 50% 100%;\n  animation: f-breathe 7s ease-in-out infinite;\n}\nbody::after {\n  content: \"\"; position: fixed; inset: 0; pointer-events: none; z-index: 2147482001;\n  background-image: url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\"); opacity: .05; mix-blend-mode: overlay;\n}\n@keyframes f-breathe { 0%,100% { opacity: .7; transform: scaleY(.96) } 50% { opacity: 1; transform: scaleY(1.04) } }\n/* bellows: while Forge is working the fire roars */\nbody:has(button[aria-label=\"Stop generating\"])::before { animation-duration: 1.6s; filter: brightness(1.5) hue-rotate(-8deg); }\n\n#forge-sparks { position: fixed; inset: 0; pointer-events: none; z-index: 2147482002; overflow: hidden; mix-blend-mode: screen; }\n#forge-sparks i {\n  position: absolute; bottom: -12px; width: 3px; height: 3px; border-radius: 50%;\n  background: radial-gradient(circle, #fff3d1 0%, #ffb257 45%, rgba(255,122,47,0) 75%);\n  box-shadow: 0 0 6px 1px rgba(255,140,50,.8);\n  opacity: 0; animation: f-spark linear infinite;\n}\n@keyframes f-spark {\n  0%   { opacity: 0; transform: translate(0,0) scale(1); }\n  8%   { opacity: 1; }\n  70%  { opacity: .7; }\n  100% { opacity: 0; transform: translate(var(--dx), -82vh) scale(.3); }\n}\n#forge-sparks i.f-busy { display: none; }\nbody:has(button[aria-label=\"Stop generating\"]) #forge-sparks i.f-busy { display: block; }\n@media (prefers-reduced-motion: reduce) { body::before { animation: none } #forge-sparks { display: none } }\n\n/* ---- the shop wall: brushed dark iron sidebar with a steel seam ---- */\n[class*=\"_sidebarCol\"] {\n  background:\n    repeating-linear-gradient(90deg, rgba(255,255,255,.012) 0 1px, transparent 1px 3px),\n    linear-gradient(180deg, #100d0b 0%, #0a0807 100%) !important;\n  box-shadow: inset -1px 0 0 var(--f-seam), inset -2px 0 0 rgba(0,0,0,.6);\n}\n/* stamped section labels */\n[class*=\"_sectionLabel\"] {\n  font: 600 10.5px/1 var(--f-mono) !important; letter-spacing: .18em; text-transform: uppercase; color: var(--f-ash) !important;\n}\n/* New Session: a forged iron plate with a hot edge */\nbutton[class*=\"_newSession\"] {\n  background: linear-gradient(180deg, #2a221b, #1a1511) !important;\n  border: 1px solid #3a2f25 !important; border-radius: 6px !important;\n  box-shadow: inset 0 1px 0 rgba(255,220,180,.07), inset 0 -2px 0 rgba(255,122,47,.35), 0 2px 0 #050403 !important;\n  font: 700 13px/1 var(--f-display) !important; letter-spacing: .12em; text-transform: uppercase; color: var(--f-bone) !important;\n  transition: box-shadow .25s, transform .1s;\n}\nbutton[class*=\"_newSession\"]:hover { box-shadow: inset 0 1px 0 rgba(255,220,180,.1), inset 0 -2px 0 var(--f-hot), 0 0 18px -4px rgba(255,122,47,.6), 0 2px 0 #050403 !important; }\nbutton[class*=\"_newSession\"]:active { transform: translateY(1px); }\n/* session rows: the selected one is a bar pulled from the fire */\n[class*=\"_sessionRow\"] { border-radius: 4px !important; position: relative; transition: background .2s; }\n[class*=\"_sessionRow\"][class*=\"_selected\"] {\n  background: linear-gradient(90deg, rgba(255,122,47,.22), rgba(255,122,47,.04) 70%, transparent) !important;\n  box-shadow: inset 2px 0 0 var(--f-ember), -6px 0 14px -6px rgba(255,122,47,.9);\n}\n[class*=\"_sessionRow\"][class*=\"_selected\"] [class*=\"_title\"] { color: #fff4ec !important; }\n[class*=\"_projectRow\"] [class*=\"_title\"] { font-weight: 600; }\n\n/* ---- the start screen ---- */\n[class*=\"_titleGroup\"] > span:first-child {\n  font: 700 46px/1.05 var(--f-display) !important; letter-spacing: -.005em; text-transform: none;\n  background: linear-gradient(180deg, #f6efe4 22%, var(--f-hot) 64%, var(--f-ember) 82%, var(--f-deep) 100%);\n  -webkit-background-clip: text; background-clip: text; color: transparent !important;\n  padding: .14em .02em .02em; filter: drop-shadow(0 0 22px rgba(255,105,35,.28));\n}\n[class*=\"_previewBadge\"] { display: none !important; }\n[class*=\"_headline\"] { animation: f-rise .9s cubic-bezier(.2,.7,.1,1) both; }\n[class*=\"_root\"][class*=\"_hero\"] > [class*=\"_card\"] { animation: f-rise .9s .15s cubic-bezier(.2,.7,.1,1) both; }\n@keyframes f-rise { from { opacity: 0; transform: translateY(14px); filter: blur(3px) } to { opacity: 1; transform: none; filter: none } }\n\n/* ---- the anvil: riveted steel plate that heats up when you work it ---- */\n[class*=\"_root\"] > [class*=\"_card\"] {\n  background:\n    radial-gradient(circle at 10px 10px, #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),\n    radial-gradient(circle at calc(100% - 10px) 10px, #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),\n    radial-gradient(circle at 10px calc(100% - 10px), #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),\n    radial-gradient(circle at calc(100% - 10px) calc(100% - 10px), #5b524a 0 1.6px, #1a1511 2.4px, transparent 3px),\n    linear-gradient(180deg, #1d1814 0%, #141009 100%) !important;\n  border: 1px solid #3a2f25 !important; border-radius: 10px !important;\n  box-shadow: inset 0 1px 0 rgba(255,220,180,.06), 0 0 0 1px #050403, 0 20px 50px -22px rgba(255,105,35,.45) !important;\n  transition: box-shadow .4s, border-color .4s;\n}\n[class*=\"_root\"] > [class*=\"_card\"]:focus-within {\n  border-color: rgba(255,154,85,.55) !important;\n  box-shadow: inset 0 1px 0 rgba(255,220,180,.08), inset 0 -3px 0 -1px rgba(255,122,47,.6), 0 0 0 1px rgba(255,122,47,.25),\n              0 0 34px -6px rgba(255,105,35,.55), 0 24px 60px -18px rgba(255,105,35,.6) !important;\n}\nbody:has(button[aria-label=\"Stop generating\"]) [class*=\"_root\"] > [class*=\"_card\"] { animation: f-glow 1.6s ease-in-out infinite; }\n@keyframes f-glow { 50% { border-color: rgba(255,178,87,.7); box-shadow: 0 0 0 1px rgba(255,122,47,.35), 0 0 40px -4px rgba(255,105,35,.7) } }\n\n/* send: a molten drop */\nbutton[aria-label=\"Send message\"] {\n  background: radial-gradient(circle at 50% 30%, #fff1d6 0%, #ffb257 28%, #ff7a2f 60%, #c2410c 100%) !important;\n  box-shadow: 0 0 16px rgba(255,122,47,.65), inset 0 -2px 3px rgba(120,30,0,.5) !important;\n  color: #1a0d05 !important; transition: transform .15s, box-shadow .2s;\n}\nbutton[aria-label=\"Send message\"]:not(:disabled):hover { transform: scale(1.08); box-shadow: 0 0 26px 4px rgba(255,140,50,.8) !important; }\nbutton[aria-label=\"Send message\"]:disabled { filter: grayscale(.55) brightness(.6); box-shadow: inset 0 -2px 3px rgba(0,0,0,.5) !important; }\nbutton[aria-label=\"Stop generating\"] {\n  background: linear-gradient(180deg, #a9b3bd, #5d6875) !important; color: #0c0a08 !important;\n  box-shadow: 0 0 0 2px rgba(255,122,47,.5), 0 0 18px rgba(255,122,47,.6) !important;\n}\n\n/* stamped readouts (tok/s, tokens, context) */\n[class*=\"_pill\"] { font-family: var(--f-mono) !important; letter-spacing: .06em; color: var(--f-gold) !important; }\n\n/* ---- the conversation ---- */\n/* your messages: a struck steel plate */\n[class*=\"_userStack\"] [class*=\"_bubble\"] {\n  background: linear-gradient(180deg, #2a2520 0%, #1f1a16 100%) !important;\n  border: 1px solid #3a2f25; border-radius: 10px 10px 2px 10px !important;\n  box-shadow: inset 0 1px 0 rgba(255,220,180,.07), 0 6px 18px -10px #000;\n}\n/* headings in the answer: hammered type */\n[class*=\"_markdown\"] h1, [class*=\"_markdown\"] h2, [class*=\"_markdown\"] h3 {\n  font-family: var(--f-display) !important; text-transform: uppercase; letter-spacing: .03em; color: var(--f-bone);\n}\n[class*=\"_markdown\"] h1, [class*=\"_markdown\"] h2 { border-bottom: 1px solid var(--f-seam); padding-bottom: .25em; }\n[class*=\"_markdown\"] strong { color: #fff4ec; }\n[class*=\"_markdown\"] li::marker { color: var(--f-ember); }\n[class*=\"_markdown\"] a { color: var(--f-hot) !important; text-decoration-color: rgba(255,178,87,.4); }\n[class*=\"_markdown\"] blockquote { border-left: 2px solid var(--f-steel) !important; color: var(--f-steel-hi); }\n/* code: blackened steel with an ember edge */\npre { border-left: 2px solid rgba(255,122,47,.6) !important; background: #0e0b09 !important; box-shadow: inset 0 0 0 1px #2a221b; }\ncode { font-family: var(--f-mono) !important; }\n[class*=\"_markdown\"] :not(pre) > code { color: var(--f-hot); background: #241d17 !important; border: 1px solid #33291f; }\n/* view tabs (Chat / Trajectory): stamped */\n[class*=\"_tabLabel\"] { font: 600 11px/1 var(--f-mono) !important; letter-spacing: .14em; text-transform: uppercase; }\n/* file cards: a tag on the workbench */\n[class*=\"_fileLink\"] { border-color: #3a2f25 !important; }\n\n/* scrollbars: cold iron, glowing on touch */\n* { scrollbar-color: #3a2f25 transparent; }\n*::-webkit-scrollbar-thumb { background: #3a2f25; border-radius: 6px; }\n*::-webkit-scrollbar-thumb:hover { background: var(--f-deep); }\n";
		// Claude-style greeting by time of day; picked once per page load.
		const NAME = "Jacob";
		const GREETINGS = {
			night:     ["Hello, night owl", "Up late, " + NAME + "?", "Back at it, " + NAME],
			morning:   ["Good morning, " + NAME, "Back at it, " + NAME, "What's new, " + NAME + "?"],
			afternoon: ["Good afternoon, " + NAME, "Back at it, " + NAME, "How's your day going, " + NAME + "?"],
			evening:   ["Good evening, " + NAME, "Back at it, " + NAME, "How was your day, " + NAME + "?"]
		};
		const hour = new Date().getHours();
		const slot = hour < 5 ? "night" : hour < 12 ? "morning" : hour < 18 ? "afternoon" : hour < 23 ? "evening" : "night";
		const HEADLINE = GREETINGS[slot][Math.floor(Math.random() * GREETINGS[slot].length)];

		// Flame mark (sidebar + start screen). Same paths as the splash emblem
		// and macos/make_icon.py.
		const FLAME_OUTER = [
			"M12 1.8",
			"C12.9 5.2 15.6 7.0 17.4 9.6",
			"C18.6 11.3 19.2 13.2 19.2 15.2",
			"C19.2 19.3 16.0 22.4 12.0 22.4",
			"C8.0 22.4 4.8 19.3 4.8 15.4",
			"C4.8 12.9 6.0 10.9 7.7 9.4",
			"C7.8 11.0 8.5 12.3 9.6 13.0",
			"C9.2 8.9 10.4 5.0 12.0 1.8 Z"
		].join(" ");
		const FLAME_INNER = [
			"M12.3 10.6",
			"C12.8 13.0 14.4 14.2 15.2 15.8",
			"C15.6 16.5 15.8 17.2 15.8 17.9",
			"C15.8 20.0 14.1 21.5 12.0 21.5",
			"C9.9 21.5 8.2 20.0 8.2 18.0",
			"C8.2 16.6 8.9 15.5 9.9 14.8",
			"C10.0 15.7 10.4 16.4 11.0 16.8",
			"C10.8 14.6 11.3 12.4 12.3 10.6 Z"
		].join(" ");
		function ForgeMark({ size }) {
			const s = typeof size === "number" ? size : 22;
			return jsxs("svg", { width: s, height: s, viewBox: "0 0 24 24", "aria-hidden": true, children: [
				jsxs("defs", { children: [
					jsxs("linearGradient", { id: "forge-flame-outer", x1: 0, y1: 0, x2: 0, y2: 1, children: [
						jsx("stop", { offset: "0%", stopColor: "#ffb257" }),
						jsx("stop", { offset: "55%", stopColor: "#ff7a2f" }),
						jsx("stop", { offset: "100%", stopColor: "#c2410c" })
					] }),
					jsxs("linearGradient", { id: "forge-flame-inner", x1: 0, y1: 0, x2: 0, y2: 1, children: [
						jsx("stop", { offset: "0%", stopColor: "#ffd08a" }),
						jsx("stop", { offset: "100%", stopColor: "#fff1d6" })
					] })
				] }),
				jsx("path", { d: FLAME_OUTER, fill: "url(#forge-flame-outer)" }),
				jsx("path", { d: FLAME_INNER, fill: "url(#forge-flame-inner)" })
			] });
		}

		// FORGE wordmark with the splash's heat gradient.
		function ForgeName() {
			return jsx("span", {
				style: {
					font: '800 20px/1 "Avenir Next Condensed", "Avenir Next", "Helvetica Neue", sans-serif',
					letterSpacing: "0.05em", textTransform: "uppercase", paddingTop: "2px",
					background: "linear-gradient(180deg, #f1e9dc 30%, #ffb257 75%, #c2410c 100%)",
					WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent"
				},
				children: "Forge"
			});
		}

		const inject = ["theme", "slots"];
		function apply(ctx) {
			// Palette (both schemes get the forge values) + force DSH's dark mode.
			ctx.effect(() => ctx.theme.overrideTokens("dsh-forge-theme", TOKENS));
			try { ctx.theme.setTheme("dark"); } catch (e) {}
			const forceDark = () => { if (!document.body.hasAttribute("data-ds-dark-theme")) document.body.setAttribute("data-ds-dark-theme", ""); };
			forceDark();
			const bodyObs = new MutationObserver(forceDark);
			bodyObs.observe(document.body, { attributes: true, attributeFilter: ["data-ds-dark-theme"] });

			// Forge styling that tokens can't express.
			const style = document.createElement("style");
			style.id = "dsh-forge-theme";
			style.textContent = CSS;
			document.head.appendChild(style);

			// Sparks rising off the hearth. Every 3rd one only flies while Forge is working.
			const sparks = document.createElement("div");
			sparks.id = "forge-sparks";
			sparks.setAttribute("aria-hidden", "true");
			for (let i = 0; i < 36; i++) {
				const s = document.createElement("i");
				if (i % 3 === 2) s.className = "f-busy";
				const size = 1.5 + Math.random() * 2.5;
				s.style.left = (30 + Math.random() * 55) + "%";
				s.style.width = s.style.height = size + "px";
				s.style.setProperty("--dx", ((Math.random() - 0.4) * 180).toFixed(0) + "px");
				s.style.animationDuration = (5 + Math.random() * 7).toFixed(2) + "s";
				s.style.animationDelay = (-Math.random() * 12).toFixed(2) + "s";
				sparks.appendChild(s);
			}
			document.body.appendChild(sparks);

			// Tab title + start-screen headline.
			const fix = () => {
				if (document.title.includes("DeepSeek Harness")) document.title = document.title.replace("DeepSeek Harness", "Forge");
				for (const el of document.querySelectorAll('[class*="_titleGroup"] > span:first-child')) {
					if (el.textContent !== HEADLINE) el.textContent = HEADLINE;
				}
			};
			fix();
			const domObs = new MutationObserver(fix);
			domObs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
			ctx.effect(() => () => { bodyObs.disconnect(); domObs.disconnect(); style.remove(); sparks.remove(); });

			ctx.slots.inject("sidebar.brand.mark", () => ctx.slots.inject("sidebar.brand.name", function* () {
				yield ctx.slots.register({ name: "sidebar.brand.mark" }, ForgeMark);
				yield ctx.slots.register({ name: "sidebar.brand.name" }, ForgeName);
			}));
			ctx.slots.inject("conversation.hero.brand.mark", function* () {
				yield ctx.slots.register({ name: "conversation.hero.brand.mark" }, ForgeMark);
			});
		}
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
