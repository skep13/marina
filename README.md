# Marina — desktop VRM assistant

A voice conversational anime character that lives on your desktop as a
transparent, always-on-top VRM avatar. She listens, types back, speaks, and
lip-syncs.

Based on [rayenfeng/riko_project](https://github.com/rayenfeng/riko_project),
with the VRM frontend built out (it was an unchecked TODO upstream) and the
pipeline split so the LLM runs on your own server.

```
   you ──speak/type──►  Mac                              your server
                        ├── Faster-Whisper (speech→text)
                        ├── HTTP ───────────────────────►  Ollama / llama.cpp
                        ◄── reply ──────────────────────────────┘
                        ├── Kokoro TTS     (reply→voice, local)
                        └── VRM avatar speaks it
```

Everything except the LLM runs on the Mac. Voice synthesis is local and takes
674 MB; see [docs/TTS-ON-MAC.md](docs/TTS-ON-MAC.md) for the trade-off that
implies, and [docs/LLM-ON-SERVER.md](docs/LLM-ON-SERVER.md) for the server side.

---

## Features

- 🪟 **Transparent desktop avatar** — frameless, always-on-top, follows you
  across Spaces and over full-screen apps
- ⌨️ **Type or talk** — text box plus global push-to-talk
- 🌊 **She starts talking before she has finished thinking** — the reply is
  streamed and spoken a sentence at a time, so the first words are out while
  the model is still writing the rest. Chunks are scheduled against the audio
  clock, so there is no seam between them
- ✋ **You can cut her off** — talk over her and she stops mid-word. What she
  actually said is what goes in the transcript, so the next thing she says
  follows from what you heard rather than from a paragraph only the server saw
- 💭 **She speaks first sometimes** — she has a life of her own and will
  occasionally mention it unprompted. Rate-limited, quiet overnight, one
  switch in the tray
- 🔧 **She can do a few things** — set a timer, read what you just copied,
  open a link, write something down. Deliberately few, all local
- 🌤️ **She knows roughly what is going on** — the time, which app you are in
  (the name, never the window title), whether the laptop is about to die
- 👁️ **She can look at your screen** — one screenshot, only when you ask, sent
  to a local vision model. No background or continuous capture, ever
- 👄 **Lip sync** with five visemes chosen by formant balance, not just a jaw
  that opens and shuts — sibilants are detected and damped
- 💄 **Lip recolour** at load time (`LIPS` in `renderer/app.js`) — the lips are
  painted into the face texture, so the pixels are repainted rather than tinted
- 💨 **Hair physics** — a simulated breeze drives the VRM's own spring bones, so
  strands lag, overshoot and settle on their own
- 👁️ **Eye animation** — micro-saccades, occasional look-aways, varied and
  double blinks, and a slow drift between neutral and a faint smile
- 🎭 **Actions become animations** — the model writes `*tilts head*`, and that
  gets stripped from the speech and performed instead of read aloud. 19 cues:
  nod, shake, tilt, shrug, lean, laugh, smile, wink, eyeroll, sigh, pout, sad,
  surprised, blush, think, brow, stare, yawn, plus a generic beat
- 🧼 **Clean speech** — markdown, emoji, code blocks, bullets and links are
  stripped before TTS, so nothing reads out "asterisk" or an emoji name
- 🧠 **Long-term memory** — durable facts are distilled out of conversations and
  injected into every future one, so she remembers you across restarts. The
  transcript itself is trimmed, so the context window stays bounded no matter
  how long you talk
- 🔊 **Voice** via Kokoro running locally — 54 voicepacks, ~4× realtime,
  blendable, with pitch shifting that preserves duration
- 🎧 **Speech recognition** via Faster-Whisper, locally, ~1 s per utterance
- 🔌 **Any OpenAI-compatible LLM** — Ollama, llama.cpp, LM Studio, vLLM, or OpenAI

---

## What leaves this Mac

Voice is entirely local, in both directions, and there is no code path that
sends recorded audio anywhere. Speech recognition is Faster-Whisper running
here; synthesis is Kokoro running here. Verified by watching the bridge's
sockets through a full round trip — microphone in, reply spoken — during which
the only connections open were the loopback ones below.

| | Stays on this Mac | Leaves this Mac |
|---|---|---|
| Microphone audio | ✅ transcribed locally | never |
| Her voice | ✅ synthesised locally | never |
| Conversation + memory | ✅ on disk here | — |
| What you said, as text | | → your LLM endpoint |
| Clipboard, when she reads it | | → your LLM endpoint |
| The frontmost app's name | | → your LLM endpoint |
| Screenshots | ✅ only when you press the button | → your vision endpoint |

The three text rows are the real answer to "is this private": they go wherever
`llm.base_url` points. Pointed at Ollama on this machine, nothing leaves at
all. Pointed at the Beelink through the SSH tunnel, they cross your own
network encrypted and reach your own hardware. Pointed at OpenAI, they go to
OpenAI — that is the trade you make by configuring it that way.

Two things worth knowing specifically:

- **Reading the clipboard sends its contents to the model.** That is what
  makes "what do you make of this error" work, and it means the tool is only
  as private as the endpoint behind it. Turn it off with `tools.clipboard`.
- **`asr.offline: true`** stops Faster-Whisper contacting Hugging Face to
  revalidate the cached model on every load. Nothing of yours was ever in that
  request, but it was the only outbound connection in the voice path, and the
  voice path is the part that most deserves to be provably local.

The bridge listens on `127.0.0.1` only, so nothing on your network can reach it.

## Where this lives

`~/marina`. **Not** Desktop, Documents or Downloads — those are TCC-protected on
macOS, and a Finder-launched app cannot read a Python venv inside them. The
symptom is nasty: Python blocks inside its own startup, before it can print
anything, so the app just hangs with no error.

If you move the folder, re-run `./build-app.sh` — the bundle records this
absolute path so it can find the venv.

## Setup

### 1. Install

```bash
./setup-mac.sh
```

Finds or installs Python 3.12 (macOS ships 3.9, which is too old for
`onnxruntime`), creates `.venv`, installs dependencies, downloads the Kokoro
voice model, and installs the app's npm packages. Safe to re-run.

> The repo's original `requirements.txt` is **GPT-SoVITS's own** dependency list
> (torch, funasr, modelscope…). None of it is needed here.
> `server/requirements-mac.txt` is what the client uses.

### 2. Configure

```bash
cp character_config.example.yaml character_config.yaml
```

The real config is gitignored — it holds your API key. Edit it:

```yaml
llm:
  base_url: "http://beelink.local:11434/v1"   # your server; empty = OpenAI
  api_key: "ollama"                           # ignored locally, must be set
  model: "qwen3:8b"

presets:
  default:
    system_prompt: |
      You are a helpful assistant named Marina.
      You speak like a snarky anime girl.

tts:
  provider: kokoro          # local. 'sovits' to use a remote GPT-SoVITS instead
  kokoro:
    voice: "af_heart"       # GET /voices lists all 54
```

### 3. Add your avatar

Put a `.vrm` at `app/models/model.vrm`, or use the model button in the app.

**VRoid Studio `.vroid` files will not work** — that's a project file containing
a proprietary binary, not a 3D model. In VRoid Studio: **Export → VRM**. Both
VRM 0.x and VRM 1.0 exports load fine.

### 4. Run

Build the app once, then launch it like any other:

```bash
./build-app.sh
```

That produces **Marina.app**, installs it to `/Applications`, and it starts the
Python bridge itself — no terminal needed. Drag it to the Dock to keep it there.

For development, the two-terminal route still works:

```bash
./start-bridge.sh     # Python: mic + Whisper + your LLM + Kokoro voice
```

```bash
./start-app.sh        # the avatar
```

---

## Using it

| Action | How |
|---|---|
| Type to her | Click the box at the bottom, press Enter |
| Talk to her | Microphone button, or **⌘⇧Space** — press once to start, again to stop |
| Cut her off | Talk over her. Or **⌘⇧.** |
| Stop her speaking first | Tray → "Let her speak first" |
| Show her your screen | Eye button, or tray → "Look at my screen". Type a question first to ask about something specific |
| Move her | Drag the top strip of the window |
| Resize her | Drag a window edge |
| Hide / show | Minus button, tray menu, or **⌘⇧H** |
| Forget the conversation | Reset button (circular arrow) |
| Quit | × button, tray menu, or **⌘⇧Q** (works from anywhere) |

The control buttons only appear on hover, so she looks clean when you're not
using her.

The status dot at bottom-left is your diagnostic: green = ready, blue pulsing =
working, red = something's wrong (the message says what).

### Microphone permission

Recording happens in the Python process, so macOS asks **the terminal you ran
`./start-bridge.sh` from** for microphone access, not the avatar app. Approve it
there the first time. If you dismissed it: System Settings → Privacy & Security →
Microphone.

---

## Docs

- **[docs/TTS-ON-MAC.md](docs/TTS-ON-MAC.md)** — the local voice, blending, and
  what it takes to get a genuinely custom one
- **[docs/LLM-ON-SERVER.md](docs/LLM-ON-SERVER.md)** — Ollama on the Beelink,
  which model to pick, and why not the ThinkPad
- **[docs/PIPER-TRAINING.md](docs/PIPER-TRAINING.md)** — training your own voice
  model, and where to actually run the training
- **[docs/GPT-SOVITS.md](docs/GPT-SOVITS.md)** — the cloning-capable alternative,
  if you move TTS back off the Mac
- **[docs/MAC-PERFORMANCE.md](docs/MAC-PERFORMANCE.md)** — measured benchmarks
  and memory on this machine

---

## Layout

```
character_config.yaml         personality, LLM endpoint, voice
server/
  marina_server.py              local HTTP bridge the app talks to
  main_chat.py                terminal-only client (no avatar)
  requirements-mac.txt        slim client deps
  process/
    config.py                 shared config loader
    asr_func/                 Faster-Whisper + microphone recorder
    asr_func/vad.py           hearing you over her own voice, for barge-in
    llm_funcs/llm_scr.py      chat-completions client, streaming, tool calls
    text_func/speech.py       splits replies into speech + animation cues,
                              and into speakable chunks while streaming
    idle.py                   when she says something unprompted
    tools/context.py          time, frontmost app, battery
    tools/registry.py         timers, clipboard, links, remembering
    vision/look.py            screenshot -> vision model
    memory/store.py           durable facts, deduped and capped
    memory/extract.py         decides what is worth remembering
memory.json                   the facts themselves (readable, editable)
    tts_func/engine.py        TTS dispatch (kokoro | sovits)
    tts_func/sovits_ping.py   GPT-SoVITS HTTP client
models/kokoro/                local voice model (~340 MB)
app/
  main.js                     Electron: transparent always-on-top window
  preload.js                  IPC bridge
  renderer/app.js             three.js + three-vrm, lip sync, chat UI
  models/model.vrm            your avatar
  test/                       render + transparency smoke tests
```

### Bridge API

`http://127.0.0.1:8765`, localhost only.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Status: LLM endpoint, TTS backend, model |
| `GET /voices` | List Kokoro voicepacks |
| `POST /chat` | `{"text": "..."}` → display text, spoken text, cues, base64 WAV |
| `POST /chat/stream` | The same, as NDJSON — one event per sentence, each with its own audio |
| `POST /interrupt` | `{"chunks": n}` — stop generating; record only the n sentences heard |
| `GET /barge/listen` | Open the mic while she talks; becomes the next exchange if you cut in |
| `GET /idle/listen` | Held open until she has something unprompted to say |
| `POST /idle/mute` | Stop her speaking first |
| `GET /idle/status` | Whether she is due, and what is holding her back |
| `POST /listen/start` | Begin recording |
| `POST /listen/stop` | Stop, transcribe, answer, synthesize |
| `POST /listen/cancel` | Discard the recording |
| `POST /voice` | Upload an audio file instead of recording |
| `POST /see` | Answer a question about a screenshot |
| `POST /reset` | Forget the conversation (memory survives) |
| `GET /memory` | Everything she remembers |
| `POST /memory` | Teach her a fact directly |
| `DELETE /memory/{id}` | Forget one fact |
| `DELETE /memory` | Wipe long-term memory |
| `POST /warmup` | Preload Whisper and the voice model |

Interactive docs at `http://127.0.0.1:8765/docs` while the bridge is running.

---

## Changes from upstream

- Built the VRM desktop frontend (`client/` upstream contains only
  `still_in_development.txt`)
- Removed the hardcoded "refer to the user as senpai" instruction from the
  system prompt
- Added a local Kokoro TTS backend, so voice runs on the Mac with no GPU
- Made TTS pluggable (`tts.provider`) — local Kokoro or remote GPT-SoVITS
- Switched the LLM to chat-completions with a configurable `base_url`, so any
  OpenAI-compatible server (Ollama, llama.cpp, LM Studio, vLLM) works
- Made GPT-SoVITS's URL configurable instead of hardcoded to `127.0.0.1:9880`
- Replaced the Windows-absolute `ref_audio_path` default
- Config is now loaded relative to the repo, not the current working directory
  (upstream only ran if you were cd'd into the repo root)
- Push-to-talk records for as long as you speak; upstream always wrote a fixed
  60-second buffer, padding every clip with silence
- GPT-SoVITS errors are detected properly — it returns JSON with a 400 on
  failure, which upstream would have written to disk as a `.wav`
- LLM failures (bad key, rate limit) return a readable message instead of a 500
- Replies are split into spoken text and animation cues, so markdown, emoji and
  roleplay actions are performed or dropped rather than read out loud
- Dropped the unused `gradio` import from the LLM module
- Split requirements: the Mac client needs 8 packages, not GPT-SoVITS's full list

---

## Credits

Built on **[rayenfeng/riko_project](https://github.com/rayenfeng/riko_project)**,
which provided the original terminal voice-chat pipeline. Its `client/` directory
was a placeholder and "VRM model frontend" an unchecked TODO — that frontend, and
everything below it, is what this repo adds.

**Avatar and rendering**
- [three-vrm](https://github.com/pixiv/three-vrm) — VRM rig, expressions, spring bones
- [three.js](https://threejs.org) · [Electron](https://www.electronjs.org)
- [VRoid Studio](https://vroid.com/en/studio) — character creation

**Speech**
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) — speech recognition
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via
  [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) — voice
- [soxr](https://pypi.org/project/soxr/) — duration-preserving pitch shift

**Language model**
- [Ollama](https://ollama.com), or any OpenAI-compatible endpoint

**Alternative backends, wired and documented**
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) — voice cloning
  ([docs](docs/GPT-SOVITS.md))
- [Piper](https://github.com/OHF-voice/piper1-gpl) — training your own voice
  ([docs](docs/PIPER-TRAINING.md))

MIT.
