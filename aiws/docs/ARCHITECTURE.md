# the AI workstation — architecture

AIWS is a Debian-based AI development workstation. Working name; the
name, colours and logo live in `build/branding.env` and `build/config/includes.chroot/usr/share/aiws/`,
so a rename is one file plus artwork.

**Decision (2026-10-27): AIWS replaces Proxmox on lab3.** lab3 becomes the
desktop you work at, with the AI part of the OS rather than a service on
a hypervisor. Marina, Songbird and llama-swap move from ct110 into AIWS
as native services. Acceptance rule for the switch: on lab3, AIWS must
match today's baseline (§1) for Marina's model before Proxmox is removed.

Status: design + first prototype. Everything below marked **(M1)** is in
the first milestone; the rest is planned.

## 1. What was found (read-only inventory, 2026-10-27)

| | lab1 | lab2 | lab3 |
|---|---|---|---|
| CPU | i5-6500, 4 threads | i5-6300U, 4 threads | Ryzen 7 255, 16 threads |
| RAM visible | 3.7 GiB (1.9 avail) | 11.6 GiB (2.9 avail) | 23.2 GiB (2.7 avail) |
| Disk | 70 GB root + 155 GB thin + 700 GB HDD | 70 GB root + 148 GB thin (30 % used) | 94 GB root + 833 GB thin (11 % used) |
| PVE | 9.2.20 | 9.2.20 | 9.2.2 (kernel 7.0.2) |
| Guests | 101 fileshare, 102 tailscale, 103 uptime-kuma, 106 rustdesk, 112 Open WebUI | 104 services, 111 marina-workspace VM (4 GiB), 113 songbird-kali (stopped), 114 dot-bridge | 110 marina-brain |

Cluster: 3 nodes, 3 votes, quorate.

lab3 GPU memory, measured:

* BIOS carve-out (VRAM): 8 GiB, **fully used** (8.57 GB).
* GTT (system RAM the GPU maps): limit 20 GiB (`amdgpu.gttsize=20480`,
  `ttm.pages_limit=5242880`), **16.7 GB used**.
* So the resident model costs ~25.3 GB of the 32 GB: 22.1 GB weights +
  0.9 GB vision projector + ~2.2 GB KV/compute. GTT counts against the
  23.2 GiB Linux sees; the carve-out does not.
* llama-server RSS 1.9 GB (prompt cache `--cache-ram 1024` + host buffers),
  Marina bridge RSS 1.0 GB, llama-swap 65 MB.
* ct110: Debian 13, Mesa 25.0.7 RADV (PHOENIX), llama.cpp `f2cc728`
  (2026-10-11), llama-swap v265.
* Cold-ish load of `marina` from service start to healthy: **23 s**.

Baseline (`ai-bench`, `bench/results/2026-10-27-lab3-baseline-marina.json`),
Qwen3.6-35B-A3B UD-Q4_K_M, `-c 131072 -ctk/-ctv q8_0 -np 2 -fa on`:

| scenario | TTFT | prompt t/s | gen t/s |
|---|---|---|---|
| chat (28 tok) | 0.42 s | 78 | 23.5 |
| code (113 tok) | 1.01 s | 121 | 24.5 |
| 2k context | 6.3 s | 325 | 23.8 |
| 8k context | 25.2 s | 318 | 22.9 |

**The central constraint.** Today lab3 has 2.7 GiB free with no desktop
at all. A desktop + browser + editor needs 3–4 GiB. A 22 GB model can't
stay resident beside a workstation without either shrinking what the GPU
holds or freeing the 8 GiB carve-out. Section 5 is the plan for that; it
is the single most important decision in this project.

## 2. Foundation choices

| Choice | Picked | Why |
|---|---|---|
| Base | **Debian 13 trixie**; kernel, firmware and Mesa from **trixie-backports** (lab3 runs PVE's 7.0 kernel today; AIWS must not fall behind it) | Same base as PVE 9 and ct110, so llama.cpp/Mesa/ROCm findings carry over and Proxmox packages remain an option. Stable, long support. No compelling reason for anything else: Fedora/Arch get newer Mesa sooner, but backports + building llama.cpp ourselves covers that. |
| Image build | **live-build** → hybrid ISO, **Calamares** installer | Debian's own tool for its official live images; config is a plain directory we version. Reproducible via a pinned `snapshot.debian.org` date and `SOURCE_DATE_EPOCH`. (mkosi considered: better for disk images, weaker installer story.) |
| Desktop | **i3 on X11**, LightDM | ~50–100 MB, so the most memory is left for models on lab3. i3's IPC reports the window tree and every focus change exactly, which gives the assistant event-driven awareness without screenshots; X11 keeps AT-SPI, xdotool and capture working. Keyboard-driven, fully scriptable; sway is the Wayland path later. |
| Editor | VSCodium (+ Continue) and Neovim | Both point at the AIWS gateway. |
| Containers | **Podman** rootless + **Distrobox** | Daemonless, low idle memory, devcontainer-compatible; distrobox for interactive per-project toolboxes. |
| Inference | **llama.cpp (Vulkan)** primary, **whisper.cpp** (Vulkan) for ASR, Kokoro for TTS (from Marina) | Measured working on the 780M today. ROCm only for training experiments (§6). |
| Model front-door | **llama-swap** (reused, already in production) | On-demand load, TTL unload, groups for co-resident small models, preload. |
| Our layer | **aiwsd** (Python, FastAPI) | Thin, ~60 MB: auth, routing, priority, model library, projects, jobs, agent, control centre. Everything else is maintained upstream software. |

## 3. Components

```
 ┌───────────────────────── AIWS workstation (lab3) ─────────────────────────┐
 │  i3 session (user)                                                        │
 │   ├ Control Centre window (WebKitGTK → aiwsd UI)   panel: model ▸ agent ■ │
 │   ├ VSCodium / Neovim / terminals (tmux "ai-<project>")                 │
 │   └ aiws-agent  (systemd --user, NoNewPrivileges)                         │
 │        tools: files · terminal · desktop (screenshot+AT-SPI+xdotool)      │
 │        every action → action log → visible history; pause/stop            │
 │                                                                           │
 │  aiwsd  :7300  (system service, user `aiws`)                              │
 │   /v1/*   OpenAI-compatible, per-client tokens, interactive>background    │
 │   /api/*  models · profiles · projects · jobs · workers · cluster · agent │
 │   /ui     Control Centre (same UI on LAN, token-gated)                    │
 │        │                                                                  │
 │        ├─ llama-swap :8080 (127.0.0.1) ─ llama-server (Vulkan, 780M)      │
 │        ├─ remote workers (SSH): lab2, lab1, ct110 while it exists         │
 │        └─ Proxmox API (read-only token) for the homelab view              │
 │                                                                           │
 │  aiws-admind (root, polkit-gated allowlist: services, GPU limits, apt)    │
 └───────────────────────────────────────────────────────────────────────────┘
```

**(M1)** = aiwsd gateway + model library + projects + jobs-over-SSH +
agent with files/terminal/screenshot + action log + stop, control centre
web UI, the image itself.

### 3.1 Model library and runtimes
`/etc/aiws/models.d/*.yaml` — one file per model: path or URL, sha256,
runtime (`llama.cpp`, `whisper.cpp`, `kokoro`, `remote`), roles (`chat`,
`code`, `vision`, `embed`, `asr`, `tts`), measured footprint, flags.
`ai models` lists, pulls and verifies; aiwsd **generates the llama-swap
config** from the library, so llama-swap stays the runtime manager and
we never hand-edit it. A model entry can also point at a remote worker
(e.g. ct110 during migration), which is how the current deployment stays
usable from day one.

### 3.2 One authenticated API
Clients (editors, agents, Marina, Open WebUI) get their own token from
`ai token new <name> --scope chat,code`. aiwsd checks it, maps role
aliases (`ai:code`, `ai:vision`, or the project's choice) to a concrete
model, and forwards to llama-swap or a worker. Two priority lanes:
interactive requests go straight through; `background` requests (agent
batch steps, embeddings, evals) wait while an interactive one is in
flight. llama.cpp slots stay at `-np 2`, so a background job never takes
the only slot.

### 3.3 Projects
`.aiws/project.yaml` in a repo (or `~/.config/aiws/projects/<name>.yaml`):
repositories, model per role, behaviour profile, environment
(`podman`/`distrobox` image or `devcontainer.json`), terminals (tmux
layout and start commands), tools the agent may use. `ai open <name>`
restores all of it: clones/pulls, starts the environment, builds the tmux
session, opens the editor, and sets the gateway's project default so
anything calling `ai:code` gets the project's model.

### 3.4 Assistant
Runs as the desktop user under a systemd user unit with
`NoNewPrivileges=yes`, so neither it nor any shell it opens can use
sudo. Tools, all scoped to the open project unless the user widens them:

* files: list/read/write/edit (Marina's `workspace.py` semantics);
* terminal: send keys to and read the project's tmux panes;
* desktop: on-demand screenshot (whole screen or focused window) **plus**
  the AT-SPI tree of the focused app, so the model gets structure and only
  pays for vision when needed; `xdotool` for clicks/typing; window events
  (focus change) are recorded without vision processing;
* jobs: submit to a worker.

Every tool call is written to the action log (SQLite) before it runs and
updated after; the control centre and the panel show it live. **Pause**
holds the next action; **Stop** (panel button, `Super+Esc`, `ai agent
stop`) kills the agent's process group and its tmux input. Admin work
goes through `aiws-admind`, which exposes a short allowlist and asks the
human via polkit every time.

### 3.5 Jobs and the homelab
Workers are registered in `/etc/aiws/workers.d/` (host, SSH user, tags
like `cpu`, `docker`, `gpu-vulkan`, `rocm`, memory cap). A job is a
command + inputs + resource limits; aiwsd picks a worker by tags and free
memory, runs it via SSH under `systemd-run --scope -p MemoryMax=…`,
streams the log and records the result. Three separate things, kept
separate:

* **dashboard integration** — read-only Proxmox API + worker heartbeats;
* **workload scheduling** — the job runner above;
* **distributed inference** — *not* in M1. llama.cpp RPC across lab1/lab2
  would be slower than lab3 alone (1 GbE, weak CPUs); revisit only if a
  model doesn't fit lab3.

Local functions never depend on a worker being up.

### 3.6 How the AI is part of the desktop
* **Super+Space — Ask.** Captures, only at that moment, the focused app
  and window, your selected text and the open project, then answers in a
  popup (Enter) or hands it to the assistant (Ctrl+Enter) with its
  actions streaming in the same popup. **(M1)**
* **Bar block** (i3blocks) of the loaded model and assistant state; **Super+Esc**
  stops the assistant from anywhere. **(M1)**
* **Event-driven awareness:** focus changes and window titles are noted
  as they happen (no vision); a screenshot is taken only when asked or
  when the accessibility tree can't answer.
* **Terminal:** a shell hook offers "explain/fix" when a command fails
  (`ai explain last`), using the tmux scrollback.
* **Files:** Thunar custom action "Ask AI about this file/folder".
* **System:** "why is the fan loud / what's using memory / update the
  system" go through aiws-admind's allowlist with a polkit prompt each
  time, since there is no Proxmox UI any more.
* **Marina** keeps her own face and voice and talks to the same gateway,
  so she and the assistant share models without swapping.

## 4. Privilege separation

| actor | runs as | can |
|---|---|---|
| user | desktop user (sudo group) | everything |
| assistant | desktop user, NoNewPrivileges, own cgroup | files in scope, tmux, desktop input, aiwsd API with its token |
| aiwsd | system user `aiws` | read models, run llama-swap, SSH to workers with its own key |
| aiws-admind | root | allowlisted ops, each confirmed via polkit |

## 5. lab3 resource budget

Physical 32 GiB. Today: 8 GiB carve-out, 23.2 GiB visible.

| | now (PVE + ct110) | AIWS, carve-out 8 GiB | AIWS, carve-out 1–2 GiB (to test) |
|---|---|---|---|
| Linux-visible | 23.2 | 23.2 | ~29–30 |
| kernel + base services | 0.9 (PVE) | 0.5 | 0.5 |
| XFCE session | – | 0.5 | 0.5 |
| browser + editor + terminals | – | 2.5 | 2.5 |
| aiwsd + agent | – | 0.15 | 0.15 |
| Marina bridge (if hosted here) | 1.0 | 1.0 | 1.0 |
| llama-server host side | 1.9 | 1.0 (`--cache-ram 512`) | 1.0 |
| **GTT available to models** | 16.7 used | **~17.5** | **~24** |
| carve-out (VRAM) | 8 | 8 | 1–2 |
| **total GPU memory for models** | 25.3 | ~25.5 | ~25–26 |

So the default "big" model still fits with the desktop, but with no
slack. The plan keeps working settings and tests alternatives in this
order, measuring each with `ai-bench` and `ai-mem`:

1. **Context.** 131k × 2 slots is mostly unused for chat/coding.
   Interactive profile `-c 32768 -np 2`; a `long` profile reloads with
   131k on demand.
2. **Tiered models instead of one big resident model.** Resident: a
   small coding/chat model (e.g. Qwen3-Coder-class 7–14B or Qwen3.6-A3B at
   Q3) ~5–9 GB; the 35B-A3B loads on demand via llama-swap (23 s). Vision
   projector loaded only by the vision profile.
3. **Carve-out.** On APUs llama.cpp Vulkan runs from GTT nearly as fast as
   from the carve-out (same DRAM). Lowering the BIOS UMA size to 1–2 GiB
   returns ~6 GiB to Linux. Needs a BIOS change on lab3 → **needs your
   approval and physical access**; benchmark before and after.
4. **Quantisation.** UD-Q4_K_M → UD-Q3_K_XL saves ~4 GB; quality checked
   with the eval workflow before adoption.
5. **Batch sizes.** `-b/-ub 1024–2048` usually lifts Vulkan prompt
   processing (318 t/s now); needs a model reload, so tested in a quiet
   window.

Responsiveness while inferring: llama-server and jobs run in a
`aiws-inference.slice` / `aiws-batch.slice` with lower `CPUWeight` and
`IOWeight` than `user.slice`; background jobs get `Nice=10`; the
compositor and input never wait on them. systemd-oomd watches the batch
slice first.

## 6. Tuning and training — three workflows

1. **Inference settings** — `ai tune`: a profile (ctx, KV type, batch,
   offload, slots, quant) is applied to a *copy* of the model entry,
   benchmarked with `ai-bench`, and only promoted if it wins. The old
   entry is kept, so rollback is one command.
2. **Behaviour** — prompts, chat templates, retrieval sources, tool sets
   and system profiles, versioned under `~/.config/aiws/profiles/`, A/B
   evaluated against a fixed question set.
3. **Weights** — LoRA/QLoRA. A run is a YAML (base model, dataset,
   hyper-parameters, seed) checked by `ai train validate` (schema,
   dedupe, token lengths, train/eval split), run as a job with checkpoints
   and live loss in the control centre, evaluated against the base model
   on the same set, exported to GGUF LoRA and deployed with llama.cpp
   `--lora`; rollback = remove the adapter from the model entry.

Compatibility, honestly: Vulkan inference working says nothing about
training. PyTorch has no Vulkan training backend. The 780M (gfx1103) is
not on ROCm's official support list; it often works with
`HSA_OVERRIDE_GFX_VERSION=11.0.0`, but bitsandbytes QLoRA on ROCm for
this chip is unverified. M2 starts with a feasibility test; the fallback
is CPU LoRA for small models (slow, but works) or a rented/remote GPU
worker registered like any other worker. llama.cpp's own finetune
example is a second option to test.

## 7. Proxmox and migration

The the AI workstation is not a PVE node by default. Options for lab3:

* **A — keep PVE, run AIWS as a guest.** Needs 780M passthrough to a VM
  (reset problems are common on Phoenix iGPUs) and leaves the host's
  display unused. Not recommended.
* **B — bare-metal AIWS, lab3 leaves the cluster (chosen).** lab1+lab2
  left as a 2-node cluster need a third vote: a **QDevice**
  (`corosync-qnetd`) on an always-on box (AIWS itself works, as it's
  plain Debian; the Songbird Pi is another candidate). ct110's services
  become native AIWS services; its models are copied to AIWS's disk.
* **C — AIWS + Proxmox packages on the same trixie base.** Proxmox
  documents installing PVE on Debian, so lab3 could stay a member. It
  works but couples the workstation to PVE's kernel, firewall and
  upgrade cadence. Kept as a fallback only.

Migration (B), each step reversible until the last:

1. vzdump ct110 to lab2 + copy `/models` (~66 GB) — verified restore.
2. AIWS runs as a VM prototype (lab2/QEMU) talking to ct110 as a remote
   worker. **← M1 is here.**
3. Install AIWS to a **separate disk or USB SSD** on lab3, dual-boot; PVE
   untouched. Benchmark the same model bare metal.
4. Add QDevice; confirm 2 nodes + qdevice quorate with lab3 powered off.
5. *(approval)* `pvecm delnode lab3`, wipe PVE on lab3.

Rollback at 3: boot PVE again. At 4: remove qdevice. 5 is the only
irreversible step.

## 8. Reuse from the Marina repo

* `server/process/tools/workspace.py` — command/file/terminal tools over
  SSH, refused-command filter → assistant file/terminal tools.
* `server/workspace/marina_desktop.py`, `marina-tmux` — XFCE settings
  and tmux handling, already against XFCE → desktop tool + project tmux.
* `server/process/vision/look.py` — image shrinking + vision call.
* `server/process/confirm.py` — ask/answer flow → pause/approve actions.
* `server/process/openai_api.py` — streaming OpenAI shapes for the gateway.
* `scripts/bench-llm.sh` → superseded by `ai-bench`.
* `songbird/display/webui` — the retro-futurist look for AIWS's branding.
* Marina herself runs on AIWS as an application against the gateway
  (`ai:chat` alias → her model).
