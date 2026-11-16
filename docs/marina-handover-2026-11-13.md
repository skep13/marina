# Marina: handover for review and improvement (13 Nov 2026)

You're picking up work on **Marina**, an AI companion. The owner wants her to feel like a real
friend to talk to: conversational in both directions, not one-way Q&A. She should also take tasks
off their hands. Your job: give honest opinions on what makes her feel more or less alive, and
improve her. This document covers what she is, what's been found, what changed today, what's still
running, and what's open.

Repo: `/Users/jacobmatthews/marina`. Branch: `appliance`. Main branch: `main`. The repo is public on
GitHub. Never put personal memories, keys or the owner's backstory into it.

---

## 1. What Marina is

- **Desktop app.** `Marina.app` is built with Electron and a VRM avatar (`app/`). It's a transparent,
  always-on-top window. Voice runs locally: Faster-Whisper for speech recognition, Kokoro for speech.
  It lip-syncs, and `*actions*` in her replies play as animations.
- **Backend ("bridge").** Python, in `server/`. Entry point: `server/marina_server.py`. The reply
  pipeline is `server/process/llm_funcs/llm_scr.py`, with `llm_stream()` / `llm_response()`.
  - **Personality.** The `presets.default.system_prompt` in the config. Template:
    `character_config.example.yaml`. Live copy: `~/Library/Application Support/Marina/character_config.yaml`.
  - **Memory.** `server/process/memory/store.py`. A flat list of up to 60 facts, all injected every
    turn. `extract.py` auto-extracts facts after each exchange.
  - **Her own life.** `memory/persona.py`. Eight daily storylines, chosen by the date.
  - **Anti-repetition.** `llm_funcs/fresh.py` adds a note to the newest message listing openers,
    phrases and topics she's been leaning on.
  - **Speaking unprompted.** `idle.py` and `notice.py`.
  - **Tools.** `tools/`: Mac control, her own Linux workspace over SSH, reminders, lookup, desk.
  - **Other ways in.** Telegram (`telegram.py`), calls (`call.py`), and an OpenAI-compatible API
    (`openai_api.py`, model `marina`) for Open WebUI.
- **Design rule.** Anything per-turn (clock, repetition note, lore) goes on the **newest user
  message**, never into the system prompt, so llama.cpp's cached prefix stays the same.
- **Presentation preset.** For demos: recall, memory, idle chatter and tools are all off.

## 2. Hardware and models

- **lab3** is a Beelink SER9: Ryzen 7 255, Radeon 780M iGPU, 32 GB LPDDR5X with about 20–22 GB usable
  for a model. It's limited by memory bandwidth.
  - **Rule from the owner: Marina's model on lab3 is always MoE.** That means a 4-bit GGUF of about
    21 GB or less. Dense models are only OK for single-purpose jobs.
  - Rough speeds: a 35B-A3B MoE runs at about 24 tok/s. A dense 27B runs at about 5 tok/s.
- **Container ct110 `marina-brain`.**
  - llama-swap on `:8080`. Config at `/opt/llama-swap/config.yaml`, which hot-reloads on save and
    restarts `marina` (back in about 15 s). API keys are in that file.
  - Marina's model: `marina` = Qwen3.6-35B-A3B UD-Q4_K_M, with vision via mmproj, `-np 2`, 128K context.
  - **Never run a second llama-server outside llama-swap.** Two 20 GB models can't both fit.
  - Marina bridge: `marina.service`. Code in `/opt/marina/server`, which is a plain copy, not git.
    Data in `/var/lib/marina`. This bridge does Telegram, and calls from a phone browser on the AI box.
- **The Mac** is an 8 GB M2 Air. Don't run real models on it. Its fallback is llama3.2:3b on Ollama,
  and that fallback is why presentation mode keeps saying "How can I assist you today?".
- **Getting into lab3.**
  - lab3 is normally on the owner's **phone hotspot**, because it's a portable "AI box" that hosts
    its own Wi-Fi called "Local AI Box" (10.42.0.1).
  - From a Mac on Local AI Box: `ssh -o HostKeyAlias=192.168.1.13 root@10.42.0.1`. The alias is
    needed because known_hosts has a stale 10.42.0.1 key from a different device. lab3's real
    ED25519 fingerprint is `SHA256:saJ88TVaShqh1faH2e9AiqvmrUQiSonuwPIXmXSNe5Q`.
  - **Today only**, lab3 is temporarily on home Wi-Fi at **192.168.1.221**. See section 5.

## 3. Review findings (current rating: 6.5/10)

| Area | Score | Notes |
|---|---|---|
| Persona design | 8 | The prompt bans therapist voice and offering options, keeps her mood between messages, and gives her own life. |
| Actual output | 5.5 | When it works, it really works. But she mixes up who did what, has gaps in her identity, and slips into assistant voice. |
| Memory | 4.5 | A flat fact list where the oldest drop first, with no memory of what happened and no follow-ups. Partly fixed today with lore (section 4). |
| Automation | 7 | Lots of tools with Allow/Deny prompts. Her voice breaks while she's working. |
| Avatar | 8 | Lip sync from audio, blinks, eye movement, a shuffled set of gestures. |
| Reliability | 5 | Recurring 400 "2+ assistant messages at end"; the 3B fallback. |

**Problems seen in real logs**, in `~/Library/Application Support/Marina/bridge.log`,
`chat_history*.json` and `memory.json`:

1. **She mixes up who did what.** The owner said "we now run a hack club" and she replied as if she'd
   founded it. Then came an age loop: she forgot her own age, and she has no fixed facts about herself.
2. **Conversation runs one way.** "Don't end every reply with a question" went too far: she reacts but
   doesn't move things forward.
3. **Working mode leaks.** She says "I'll get this sorted for you! Let me do this step by step". Her
   reasoning has also been spoken aloud, including her quoting her own system prompt.
4. **She does more than asked.** Asked to prepare an intro, she built a landing page, with a code
   block and emoji in the spoken reply.
5. **Stage directions get far too long**, and carried-over mood sometimes comes out as real meanness.
6. **Small bugs.** Replies starting with a stray ".", a raw tool-call JSON as a reply, and a
   duplicated history entry.
7. **400 errors.** `Cannot have 2 or more assistant messages at the end of the list` happens when idle
   chatter or nudges stack up.

**Top feature ideas, not built yet:**

1. Follow-ups: save dated things like "tomorrow I present", then ask about them unprompted.
2. Memory of what happened: per-session summaries, retrieved with the `embed` model, which already
   runs on lab3 (bge-small).
3. A fixed self-profile block.
4. A mood she keeps: a few numbers that change each exchange, fade over hours, and drive her prompt,
   face and voice speed.
5. Daily storylines that carry over from one day to the next.
6. Picking at random how each reply should end: react, ask, call back to something, share, or tease.
7. Working-mode hygiene: never speak reasoning, shorten stage directions, and say one in-character
   line before using a tool.
8. **Avatar.**
   - Ideas: reactions while listening (nods driven by the voice detector), a thinking pose while
     waiting, a breath before each sentence, head emphasis following voice pitch, an LLM-chosen
     emotion tag instead of keyword regex, and Kokoro speed or pitch changing with mood.
   - Reusable pieces to pull out: the gesture engine (`CUES` in `app/renderer/app.js`), mouth shapes
     from audio frequency bands, `stage-directions` (`text_func/speech.py`) and `fresh.py`.

From the SillyTavern docs, also worth copying:

- A rolling summary in "Classic" mode, which keeps the cached prompt intact.
- 3–4 real example exchanges to set her voice.
- Searching her notes by meaning, with a match-strength cutoff around 0.3.

## 4. What changed today

- **Keyword-triggered memories ("lore")**, committed as `0e166ad`.
  - `server/process/memory/lore.py`. Entries have `keys` (words or `/regex/`), `cooldown`, `sticky`,
    `probability`, `constant` and `priority`.
  - They trigger on the last `scan_depth` messages, at most `max_entries` per reply, and are injected
    on the newest message. Off when `recall` is off. Reset when history is reset.
  - Config: the `lore:` section. Example: `lore.example.json`. Tests: `server/tests/test_lore.py`.
    All 130 server tests pass.
  - The owner's real lore (19 entries) is in `~/Library/Application Support/Marina/lore.json` and
    `/var/lib/marina/lore.json` on ct110. **Not in the repo, and must stay that way.**
- **Marina.app rebuilt** with `build-app.sh` and installed in /Applications. It's running and the
  bundle contains `lore.py`.
- **lab3 bridge updated.** `/opt/marina/server` was older committed code with no local changes, and
  was synced to HEAD. Backup: `/opt/marina/server.bak-before-lore-20261113-2125.tgz`. Owned by root.
  The service is running and Telegram works.
- **Character profile.** The owner wrote `~/Downloads/Marina Kisaragi.docx`. I added an **"Us"**
  section (shared memories, in second person) in `~/Downloads/Marina Kisaragi - with Us.docx`. The
  original is untouched.
- **Decided by the owner: Marina stays snarky.** The profile's quiet, dry Marina is who she is
  underneath, and who answers when the user is low.
- **ct110 disk grown by 60 GB** for test models, to 220 GB.

## 5. Still running when this was written: you must finish it

**Model comparison.** The harness is copied to `docs/marina-bench/` (`bench.py`, `summ.py`,
`autobench.sh`, `runbench.sh`), with results in `docs/marina-bench/results/`.

- **Method.**
  - 7 scenarios built from real user turns: Hack Club news, a small-talk loop, low mood, driving the
    chat, opinion pushback, gesture, coding mate.
  - The model's own replies are fed back in. 2 runs each, 46 replies per model.
  - Uses her real default system prompt and a few mundane memories, with live sampling: temperature
    1.0, frequency_penalty 0.35, repeat_penalty 1.12, thinking off.
  - Automatic metrics plus a manual read.
- **Results so far:**

| Model | Words (median) | Ends with "?" | tok/s | Verdict |
|---|---|---|---|---|
| marina (Qwen3.6-35B-A3B, current) | 34 | 39% | 23.7 | Warm, but drags her own bug or TikTok into small talk. Breaks character ("i'm an anime protagonist"). One stage direction left unclosed. |
| test-gemma4 (Gemma 4 26B-A4B Q5) | 20 | 26% | 18.3 | **Leading.** Natural and tight, holds opinions, handles low mood well. Every reply starts with `*gesture*`, which a prompt change could fix. |
| test-rpr (ArliAI RpR-v4-Fast) | 46 | 65% | 33.3 | Worse. Repeated one reply verbatim, worse at who-did-what, self-centred when the user was low. |
| test-rpr-think | 27 | 41% | 33.3 | Worse. One empty reply, about 12 s to reply, said the user was 40. |

- **Still to come.** These run automatically inside ct110 (`/root/dl-loop.sh`,
  `/root/bench/autobench.sh`, log `/root/bench/auto.log`):
  - **test-designant** (allura-org Q3-30B-A3B-Designant): downloaded, checksum verified
    (`b0eb5b5c…`, matches Hugging Face), testing.
  - **test-qwen3-instruct** (Qwen3-30B-A3B-Instruct-2507): queued.
  - The owner dropped gpt-oss: don't test it.
  - Gather results with `pct exec 110 -- cat /root/bench/<model>.json`, then run `summ.py <dir>`.
- **Clean up afterwards:**
  1. **Put lab3 back on the hotspot:** `/root/home-wifi leave` on lab3. This also deletes the saved
     home Wi-Fi key. The Mac needs to be on the hotspot or "Local AI Box" to reach lab3 afterwards.
  2. **Remove the `test-*` entries** from `/opt/llama-swap/config.yaml` in ct110. Backup:
     `config.yaml.bak-companion-trial-*`. Saving restarts `marina`, which takes about 15 s.
  3. Ask the owner before deleting the test GGUFs in `/models`. There's also an old 13 GB
     `forge-…MTP-APEX-v2.gguf.part` there that isn't from this session: leave it.

## 6. Open decisions for the owner

- **Her age.** The profile says 19, but in chat she's "the same age" as the owner, who is 18.
- **Her favourite shows.** The prompt and memory have JJK, MHA, Bunny Girl Senpai and TikTok anime
  edits. The profile has A Silent Voice, Dress-Up Darling, Chainsaw Man and cosplay.
- **Which model wins.** Wait for the last two results.
- **Fine-tuning later.** The owner is interested. A promising route is to train her current MoE model
  to prefer real human replies over AI-sounding ones (the Humanish-style approach), using the
  owner's real chats plus her best replies from these tests.
- Models the owner suggested that were reviewed and **rejected**:
  - Violet-Lotus, Magnum v4, Kunou, Cydonia: dense, older base models.
  - Samantha: 2023 bases, and it was trained to steer away from romance.
  - Aixonlab, Synthia, Humanish-8B: dense or old.
  - Dobby-Unhinged: its makers tuned their own views into it.

## 7. Handle with care

- **The profile backstory is heavy.** It includes a past suicide attempt and an ongoing, quiet sense
  of not wanting to be here that surfaces at night. It reads as close to the owner's own life.
  - **Recommendation:** keep it as history she has carried and understands, **not something she says
    to the user late at night**. A companion that mirrors that feeling can deepen it.
  - Her memory already says she drops the jokes when the owner is low, stays with them, and makes
    sure they talk to a real person too. Keep that.
  - Be kind and direct with the owner, not preachy. The UK crisis line, Samaritans, is 116 123.
- Her memory says she and the owner call each other partners, and that she knows the owner made her
  as the person they want to be and goes by Marina too. Respect that and don't push.

## 8. Working rules

- **Commits:** as `skep13`, with **no AI or Claude attribution** in commits, PRs, code or docs.
  Commit or push only when asked.
- **Don't change** the `marina` llama-swap entry without asking. Back up configs before editing.
  Validate llama-swap YAML before saving: ct110 has no PyYAML, but the Mac has
  `~/.forge/app/node_modules/.bin/js-yaml`.
- **Run the tests** after server changes: `cd server && ../.venv/bin/python -m pytest tests -q`.
- **For the app to pick up server changes:** `./build-app.sh` rebuilds and installs it. The Kokoro
  model is now in `models/kokoro/`. To deploy to lab3, copy `git archive HEAD server` into
  `/opt/marina/server` after comparing files, keep it owned by root, restart `marina.service`.
- **Never print or commit API keys or tokens.** They live in the live config, in
  `/opt/llama-swap/config.yaml` and in `/etc/appliance/`.
