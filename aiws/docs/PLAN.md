# the AI workstation — first release and phased plan

Goal: AIWS replaces Proxmox on lab3 and is the desktop you work at, with
the assistant built in. Marina's performance must not drop: the switch
happens only once AIWS on lab3 matches the baseline (~24 tok/s
generation, ~320 tok/s prompt, 0.4 s first token on a short chat).

## First release (0.1) scope

In:

* Bootable hybrid ISO (BIOS + UEFI), live session, Calamares installer.
* i3 desktop (stock look), bar block (loaded model, assistant state),
  Control Centre, `Super+Space` ask and `Super+Esc` stop.
* aiwsd: one authenticated OpenAI-compatible API, model library generating
  llama-swap's config, role aliases (`ai:code` …), per-project model
  choice, interactive/background lanes, request timings.
* llama.cpp (Vulkan, pinned to production's commit) + llama-swap (pinned).
* Projects: `ai init / open` restore repos, tmux terminals, environment
  (distrobox/podman) and editor.
* Assistant: files, project terminal, desktop (AT-SPI tree, on-demand
  screenshot + vision, xdotool), jobs; action history; pause/stop;
  no admin rights.
* Jobs on registered workers over SSH with memory caps; `local` always works.
* Homelab view: workers + Proxmox (read-only token).
* `ai-bench`, `ai-mem` for every performance claim.
* Super+Space Ask popup with desktop context; Super+Esc stop.
* Backports kernel/Mesa (at least as new as lab3's PVE stack).
* Marina's bridge and Songbird as native AIWS services; Marina and the
  coding assistant share one loaded model by default, so they don't swap.
* aiws-admind with a short allowlist (services, updates, logs, power),
  because Proxmox's UI goes away.

Out of 0.1 (planned): training workflow
UI, retrieval, voice in the desktop, distributed inference, Wayland,
Secure Boot signing, our own apt repository.

## Phases

| phase | result | touches lab3? |
|---|---|---|
| **0. Inventory + baseline** ✔ | ARCHITECTURE.md §1, baseline JSON | read-only |
| **1. Build system + VM prototype** ← now | ISO built on lab2 ct120, boots in a VM, talks to ct110 | no |
| **2. M1 demo** | desktop → `ai open` → model choice → assistant acts → job on lab2 → bench vs ct110 | no (uses ct110 remotely) |
| **3. Bare-metal trial** | AIWS on a USB SSD / second disk on lab3, dual-boot; PVE untouched | reboot of lab3 = Marina offline for the trial window — **approval** |
| **4. Tuning on hardware** | context/tiering/batch/quant experiments; carve-out test (BIOS) | **approval** for BIOS + reboots |
| **5. Training feasibility** | ROCm-on-gfx1103 test, CPU LoRA fallback, remote worker path | lab3 time while AIWS is booted |
| **6. Migration** | QDevice, ct110 services native on AIWS, lab3 leaves cluster | **approval** for each irreversible step |

## Milestone 1 — demonstration script

1. Boot the ISO (VM), log in automatically as `user`.
2. `ai status`, Control Centre open: memory, GPU, nothing loaded.
3. `ai init ~/src/demo && ai open demo` — tmux + editor come back.
4. Pick a model: `ai models use code lab3-marina -p demo` (and the local
   `qwen2.5-coder-1.5b` on the VM's CPU, to show the local runtime).
5. `ai ask "run the tests, fix the failing one, run them again"` — the
   action history fills, the terminal shows the commands, Stop works.
6. `ai job run --tags build -f 'make -C ~/demo bench'` → runs on lab2.
7. `ai-bench` through aiwsd vs straight at ct110; `ai-mem` of the
   desktop at idle and with the assistant working.

## Experiments queue (each: baseline → change → `ai-bench` + `ai-mem` → keep or roll back)

1. `-c 32768` interactive profile vs current 131072 (memory, TTFT).
2. `-b 2048 -ub 1024` / `-ub 2048` on Vulkan (prompt t/s, now ~320).
3. Q3_K_XL vs Q4_K_M (speed, memory, eval score).
4. Small resident coder + on-demand 35B (switch time, desktop headroom).
5. Carve-out 8 → 2 GiB (BIOS) with GTT 26 GiB.
6. Concurrency: `-np 1/2/4` while a background job runs; desktop input
   latency measured with `ai-bench` running alongside `xdotool` timing.

## Quorum and recovery (before lab3 leaves)

* QDevice on an always-on host outside lab1/lab2 (the Pi or AIWS itself),
  tested by powering lab3 off and checking `pvecm status` shows 3 votes.
* vzdump of ct110 to lab2 with a test restore; `/models` copied (66 GB).
* Documented rollback: boot PVE from its untouched disk; `pvecm` unchanged
  until step 6.
