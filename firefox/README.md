# Browser agent (Firefox)

A plain AI agent in the Firefox sidebar: no persona, Songbird's steel and crimson
look, running on lab3. Version 0.1 is chat only. Reading pages, clicking,
filling forms and tabs come next (see `../docs/firefox-extension-plan.md`).

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

- **think** toggles reasoning: on is slower and better at multi-step tasks; the
  trace is folded under "thought".
- **new** starts a fresh session; the conversation isn't saved anywhere.
- **Enter** runs, **Shift+Enter** adds a line, **Esc** or **stop** cuts the
  reply off.

## Files

| Path | What |
|---|---|
| `manifest.json` | Firefox MV3 manifest; host permission for lab3 only |
| `lib/lab3.js` | Settings, the system prompt, and the streaming llama-swap client |
| `sidebar/` | The sidebar panel |
| `options/` | Endpoint, key and model settings |
| `icons/` | `icon.svg` and its PNG sizes (`rsvg-convert -w N -h N icon.svg`) |

## lab3 side

The `browser` entry and the extension's own API key live in
`/opt/llama-swap/config.yaml` on lab3 (ct110). llama-swap reloads that file by
itself. To revoke the extension, delete its key line there.

## Trying it without Firefox

`sidebar/sidebar.html` also runs as a plain web page (settings fall back to
`localStorage`), e.g. via the `marina-firefox` entry in `.claude/launch.json`,
which serves this folder on port 4340.
