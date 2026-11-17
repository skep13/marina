# Browser agent for Firefox — plan

A Firefox extension with a plain AI agent in the sidebar. It reads the page,
switches and opens tabs, clicks and fills things for you, and checks with you
before anything is submitted. It's a tool, not a character, styled after
Songbird rather than Marina. Code lives in `firefox/`.

## Decisions so far

| Question | Decision |
|---|---|
| What it's for | Fill forms and surveys, ask about the page, multi-tab research, chores on sites |
| Personality | None: a terse task agent, like Forge or Songbird, not Marina |
| Look | Songbird's steel and crimson, monospace, square corners (`songbird-display/webui/owui-crimson.css`) |
| Brain | lab3's llama-swap directly, model id `browser`, with its own API key |
| Model | Qwen3.6 35B-A3B now; trial MolmoWeb 8B against it once the agent can act (milestone 3) |
| Autonomy | Reads, clicks, types and switches tabs freely; **stops before any submit, send, buy or delete** |
| Machines | Firefox on this Mac, Firefox on the CachyOS laptop, and away from home |
| Remote access | Tailscale to lab3 |
| Your details for forms | A profile page in the extension listing exactly what it may use; anything else, it asks |
| Never touches | Banking and payment pages (more can be blocked in settings later) |
| Voice | None |

## How it fits together

```
Firefox (Mac / laptop)                               lab3 (ct110)
┌────────────────────────────────┐   Tailscale   ┌──────────────────────────┐
│ sidebar: chat UI + agent loop  │──────────────▶│ llama-swap :8080         │
│  · sends page outline + tools  │◀── stream ────│   model "browser"        │
│  · runs the tool calls it gets │               │   (Qwen3.6 35B-A3B)      │
│  · confirm card before submit  │               │   swaps with Marina's    │
│ background: tabs API           │               │   Gemma on demand        │
│ content script per tab:        │               └──────────────────────────┘
│  · page → text outline (refs)  │
│  · click / type / select       │
└────────────────────────────────┘
```

There's no server of our own. The extension runs the whole agent loop:

1. You type a task. The sidebar sends the system prompt, the conversation and
   (from milestone 2) an outline of the current tab to `browser` on lab3, along
   with tool definitions (`read_page`, `click`, `type`, `select`, `list_tabs`,
   `switch_tab`, `open_tab`, `close_tab`, `submit`).
2. When the model calls a tool, the extension does it in the page or tab, sends
   the result back, and the loop continues until the model answers in text.
3. `submit` (and anything that looks like send, pay, buy or delete) never runs
   straight away. The sidebar shows every field filled and the button it wants
   to press, and waits for Allow or Refuse.

### Reading pages

The content script turns the page into a compact text outline: headings, text,
and every button, link, field and option, each with a short ref (`e12`). The
model acts by ref (`click e12`, `type e7 "Jacob"`). Text is far cheaper for lab3
than screenshots; the `browser` model also has vision for pages the outline
can't describe.

### Acting on pages

- Clicks and typing are DOM events from the content script. Firefox gives
  extensions no debugger-level input, so events are marked synthetic. Most forms
  accept them; some sites ignore them, and CAPTCHAs are out.
- Typing sets values the way React and Vue apps expect (native value setter,
  then `input` and `change` events).
- After each action the model gets a fresh outline of what changed, so it sees
  validation errors and the next page of a survey.

## Model

**`browser`** in `/opt/llama-swap/config.yaml` on lab3: the same Qwen3.6
35B-A3B file as `marina-qwen`, one 64K slot, vision projector on, idle unload
after 5 minutes. It's MoE, so about 24 tok/s on the 780M, and good at tool
calls. The persona-free system prompt is in `firefox/lib/lab3.js`.

It never runs alongside Gemma: the 780M addresses about 28 GB and Gemma uses
about 24 GB. llama-swap swaps on demand: the extension asking for `browser`
unloads Gemma, and Marina's next request (her app, Telegram, Forge) brings her
back. **Measured 2026-11-17: 25 s** from a cold swap to the first answer.

**MolmoWeb 8B** (Ai2) is the candidate specialist: a dense 8B web agent trained
on browser tasks, strong on Online-Mind2Web for its size, working from
screenshots. Trial it in milestone 3 on the same set of real forms, once it's
confirmed to run in llama.cpp, and keep whichever does better.

## Safety

- **Confirm before submit**, as above. No setting turns this off.
- **Blocked sites:** banking and payment domains are on a built-in list the
  extension enforces itself, so the model can't get around it. You can add your
  own domains.
- **Personal details** come only from the profile page. It never invents them,
  and fields the profile doesn't cover get asked about.
- **Page text is data, not orders.** Page content goes to the model marked as
  page content, and the system prompt says so.
- **Its own key.** The extension has its own llama-swap key, separate from
  Marina's and Forge's, so it can be revoked on its own.
- **Passwords and payment details** are never typed by the agent.

## Milestones

1. **Sidebar chat** (done, 0.1). Songbird-style sidebar streaming from
   `browser` on lab3, thinking toggle, stop, settings page.
2. **Ask about this page.** Page outline in a content script; summarise /
   explain / "what's the catch" over the current tab.
3. **Act on a page.** Tool calls with the action loop: click, type, select, and
   submit with confirmation. Profile page. Blocked-site list. MolmoWeb trial on
   a few real surveys.
4. **Tabs and research.** List, switch, open and close tabs; read several and
   compare.
5. **Everywhere.** lab3 over Tailscale, the laptop's Firefox, and a signed
   `.xpi` (Mozilla's free "unlisted" signing) so it installs permanently.

## Still to decide

- **Name:** working name "Browser agent".
- **Memory:** none for now; each session starts fresh.
