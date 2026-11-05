# Mac agent: Marina and Songbird driving this Mac

A Claude-Code-style agent loop that lets your own models run multi-step tasks
on this Mac — shell, files, the screen (look/click/type/keys), and the web.
It talks straight to lab3's llama-swap, not Marina's chat bridge, and reuses
the bridge's tested Mac tools in `server/process/tools/`.

```
server/agent/bin/marina-do   "find every TODO under ~/marina and summarise them"
server/agent/bin/songbird-do "list listening ports and what process owns each"
marina-do --dry-run "..."        # show the tool calls, change nothing
marina-do --steps 20 "..."       # cap the tool rounds
```

Put the two scripts on your PATH (e.g. symlink into `~/.local/bin`) to call
them as `marina-do` / `songbird-do`.

## The two personas (`personas.py`)

| | model (lab3) | shell | files | secrets | screen |
|---|---|---|---|---|---|
| **marina** | `marina` | refuses `rm`/`sudo`/`dd`/… | home folder only | shielded | yes |
| **songbird** | `songbird` | **runs anything** | **anywhere** | shielded* | yes |

Songbird runs with the command-safety gate and home-confinement **off** — your
explicit choice, since it's the security-research persona on your own machine.
Offensive tooling and any work against targets stays on the isolated Kali box
(10.10.10.10), reached over SSH / the job runner, not run here.

\* `shield_secrets` still blocks reads of `~/.ssh`, keychains and password
vaults even for Songbird. To lift even that, set `shield_secrets=False` on
`SONGBIRD`'s policy in `personas.py`.

## Always on, both personas

- **Logging:** every tool call is printed and appended to
  `~/.marina/agent-<persona>.log`.
- **Stop:** `touch ~/.marina/agent.stop` halts the loop before the next step;
  so does Ctrl-C.
- **Step cap:** `policy.max_steps` (default 40), or `--steps`.

## Driving apps (the screen)

Both personas work in a see-act-see loop: screenshot → one action → screenshot
to check. To work in an app they `focus_app` it first (which launches it if
needed and confirms it's frontmost), then prefer keyboard shortcuts (`cmd+n`,
`cmd+l`, `cmd+s`, `return`) over clicking buttons by description. Screen
reading, shell, files and the web are fast and reliable; GUI control works but
is slower and benefits from the shortcut-first approach.

Vision (screenshots and click-by-description) always goes to the `marina`
model, the only one on lab3 with a vision projector. For **Songbird** that
means each screenshot makes llama-swap swap to `marina` and back, so GUI tasks
as Songbird are noticeably slower (~80s/step). Marina drives the screen faster
because her own model has the eyes — prefer Marina for heavy GUI work.

## Web UI (drive it from a browser or phone)

Prefer a browser over the terminal — the same loop, streamed live:

```
server/agent/bin/agent-web                     # http://127.0.0.1:7420
server/agent/bin/agent-web --host 0.0.0.0 --port 7420   # serve on the LAN
```

Open the page, pick **Marina** or **Songbird** (each card shows its policy —
home-only vs anywhere, safe vs unrestricted shell, secrets shielded, screen),
type a task, optionally set a step cap or tick **dry-run**, and press **Run**.
The timeline streams every tool call with its arguments and result, colour-coded
**ok / refused / error** and collapsible; the model's own text and the final
answer show inline. The red **Stop** button touches the same
`~/.marina/agent.stop` the CLI uses, halting the loop before its next step.

It's stdlib-only (no FastAPI needed) and runs under the same `python3` as the
CLI, so there's nothing extra to install. One run at a time; a phone that
reloads mid-run reattaches to the live stream. Host/port also come from
`AGENT_WEB_HOST` / `AGENT_WEB_PORT`. Keep it on `127.0.0.1` unless you mean to
expose it — the UI applies each persona's full policy, but it adds no auth of
its own, so anyone who can reach the port can drive the agent.

## The lab3 key (not in the repo)

Each persona reads its key from the environment or a git-ignored keys file:

```
MARINA_LAB3_KEY=...        # or in ~/.marina/agent-keys.env (chmod 600)
SONGBIRD_LAB3_KEY=...
```

`~/.marina/` and `server/agent/agent-keys.env` are git-ignored. Never commit a
key. If Marina and Songbird share one llama-swap key, set both to it.

## Requirements

- Runs on macOS (uses `screencapture`, `/bin/zsh`, the bridge's Mac tools).
- Screen control needs Screen Recording + Accessibility granted to whatever
  runs it (Terminal/iTerm), in System Settings → Privacy & Security.
- lab3 reachable at `http://192.168.1.15:8080` (home LAN, or Tailscale).
