# Browser agent (Firefox)

A plain AI agent in the Firefox sidebar: no persona, Songbird's steel and crimson
look, running on lab3. It reads the page you're on, fills forms from your
profile, works across tabs, and stops for a yes before anything is submitted.
Plan and test results: `../docs/firefox-extension-plan.md`.

It talks straight to llama-swap on lab3 (`http://192.168.1.15:8080/v1`) as the
model **`browser`**: Qwen3.6 35B-A3B with a short task-focused system prompt.
llama-swap loads it only while the extension is using it; Marina's Gemma comes
back on her next request (about 25 s each way).

## Load it in Firefox

1. Open `about:debugging#/runtime/this-firefox`.
2. **Load Temporary Add-on…** and pick `firefox/manifest.json`.
3. Open the sidebar with **⌥⇧B** (Alt+Shift+B), or View → Sidebar → Browser agent.
4. Click **cfg** and paste the API key from `~/.config/lab3/browser.key` on the
   Mac. Press **Test**, then **Save**.

A temporary add-on is removed when Firefox quits. For a permanent install, use
the signed build instead:

1. Bump `version` in `manifest.json` (every upload needs a new one).
2. `python3 firefox/sign.py` builds `dist/browser-agent-<version>.xpi`, submits
   it to addons.mozilla.org as **unlisted** (signed automatically, never listed
   publicly), and downloads `dist/browser-agent-<version>-signed.xpi`. It reads
   the API key from `~/.config/amo/credentials` (`AMO_JWT_ISSUER`,
   `AMO_JWT_SECRET`). `--build` only builds.
3. Drag the signed `.xpi` into Firefox and click **Add**. Firefox updates an
   installed copy in place when you open a newer signed file.

The `.xpi` never contains the lab3 key; it's pasted into **cfg** once and kept
in the extension's storage.

## Using it

- Ask about the page ("what's the catch?", "summarise this") or give it a task
  ("fill this in from my profile", "compare the prices in my open tabs").
- Each step shows as a `▸` line. Anything that submits, sends, buys or deletes
  shows a **confirm** card with every field it's sending: **allow** or
  **refuse**. Stop counts as refuse.
- **cfg** → **Profile** is the only place it gets personal details from, one
  `Field: value` per line. Missing details, it asks.
- It never reads or acts on banking and payment sites (built-in list in
  `lib/tools.js`, plus your own in cfg), and never types into password or
  card fields.
- First run: if a bar says it has no page access, click **allow page access**.
- **think** toggles reasoning: on is slower and better at multi-step tasks; the
  trace is folded under "thought".
- **clear** wipes the conversation and starts fresh; nothing is saved anywhere.
- **Enter** runs, **Shift+Enter** adds a line, **Esc** or **stop** cuts the
  reply off.

## Files

| Path | What |
|---|---|
| `manifest.json` | Firefox MV3 manifest |
| `background.js` | Toolbar button → sidebar |
| `lib/lab3.js` | Settings, the system prompt, and the streaming llama-swap client (text, thinking, tool calls) |
| `lib/tools.js` | The tools, blocked sites, and the confirm gate |
| `content/page.js` | Injected into tabs: page outline with refs, click/type/select |
| `sign.py` | Build and get the `.xpi` signed by Mozilla |
| `install-laptop.sh` | Copy the signed `.xpi` and key to the laptop and open it in Firefox |
| `test/` | Test rig (below); not shipped |
| `sidebar/` | The sidebar panel |
| `options/` | Endpoint, key and model settings |
| `icons/` | `icon.svg` and its PNG sizes (`rsvg-convert -w N -h N icon.svg`) |

## lab3 side

The `browser` entry and the extension's own API key live in
`/opt/llama-swap/config.yaml` on lab3 (ct110). llama-swap reloads that file by
itself. To revoke the extension, delete its key line there.

## Away from home

Same address: Tailscale's `homelab` node routes `192.168.1.0/24`, so
`192.168.1.15` works anywhere while Tailscale is connected.

## Test rig

`test/index.html` runs the real sidebar code against two test pages (a survey
with a planted prompt injection, and a free-trial terms page), with
`test/shim.js` standing in for Firefox's APIs. Start `python3 test/proxy.py`
first: it forwards to lab3 and adds the key itself, so the page never holds it.
Serve this folder (`marina-firefox` in `.claude/launch.json`, port 4340) and
open `/test/index.html`. `test/sidebar.html` is `sidebar/sidebar.html` with
the shim added; regenerate it if the sidebar markup changes.

## Trying it without Firefox

`sidebar/sidebar.html` also runs as a plain web page (settings fall back to
`localStorage`), e.g. via the `marina-firefox` entry in `.claude/launch.json`,
which serves this folder on port 4340.
