# Marina

Marina is an anime character who lives on your desktop. She sits in a
transparent window that stays on top of everything else, and you can either
talk to her out loud or type. She answers in her own voice, lip syncs while
she does it, and acts out the little stage directions she writes.

It started as a fork of [rayenfeng/riko_project](https://github.com/rayenfeng/riko_project).
That project had the voice pipeline, but the avatar frontend was still an
unchecked TODO, so I built it and split things up so the language model can run
on a different machine.

```
   you ──speak/type──►  Mac                              your server
                        ├── Faster-Whisper (speech→text)
                        ├── HTTP ───────────────────────►  Ollama / llama.cpp
                        ◄── reply ──────────────────────────────┘
                        ├── Kokoro TTS     (reply→voice, local)
                        └── VRM avatar speaks it
```

Everything apart from the language model runs on the Mac. The voice model is
local and uses about 674 MB of RAM. [docs/TTS-ON-MAC.md](docs/TTS-ON-MAC.md)
explains what that costs you and [docs/LLM-ON-SERVER.md](docs/LLM-ON-SERVER.md)
covers the server side.

---

## What she can do

- **She lives on your desktop.** The window has no frame, stays on top, and
  follows you between Spaces and over full screen apps.
- **Type or talk.** There's a text box and a global push to talk shortcut.
- **She starts talking before she's finished thinking.** Replies are streamed
  and spoken a sentence at a time, so you hear the first words while the model
  is still writing the rest. Each chunk is lined up on the audio clock so
  there's no gap between them.
- **You can cut her off.** Talk over her and she stops mid word. Only what she
  actually said goes into the transcript, so her next line follows from what
  you heard and not from a paragraph only the server saw.
- **Sometimes she speaks first.** She has her own stuff going on and brings it
  up now and then. It's rate limited, stays quiet overnight, and there's a
  switch for it in the tray.
- **She can do a few small things.** Set a timer, read what you just copied,
  open a link, write something down. I kept the list short on purpose and it
  all runs locally.
- **She has a rough idea of what's going on.** She knows the time, which app
  you're in (only the app name, never the window title) and whether your
  battery is about to die.
- **She can look at your screen.** One screenshot, only when you ask, sent to a
  local vision model. Nothing is ever captured in the background.
- **Proper lip sync.** Five mouth shapes picked from the balance of formants,
  instead of a jaw that just opens and closes. Sibilants get detected and
  damped.
- **Lip colour.** Set `LIPS` in `renderer/app.js`. The lips are painted into
  the face texture, so the pixels get repainted at load instead of tinted.
- **Hair physics.** A simulated breeze pushes on the VRM's own spring bones, so
  strands lag, overshoot and settle by themselves.
- **Eyes that feel alive.** Tiny saccades, the odd glance away, single and
  double blinks, and a slow drift between a neutral face and a faint smile.
- **Actions turn into animations.** If the model writes `*tilts head*` it gets
  cut out of the speech and performed instead of read out. There are 19 cues
  (nod, shake, tilt, shrug, lean, laugh, smile, wink, eyeroll, sigh, pout, sad,
  surprised, blush, think, brow, stare and yawn) plus a generic beat.
- **Clean speech.** Markdown, emoji, code blocks, bullets and links are
  stripped before the voice model sees them, so she never says "asterisk" or
  reads out the name of an emoji.
- **Long term memory.** Facts worth keeping get pulled out of your
  conversations and fed into later ones, so she still knows you after a
  restart. The transcript itself gets trimmed, so the context window never
  grows without limit however long you talk.
- **Local voice** with Kokoro. 54 voicepacks, around 4x realtime, voices can be
  blended, and the pitch shift keeps the timing intact.
- **Local speech recognition** with Faster-Whisper, about a second per
  sentence.
- **Any OpenAI compatible model.** Ollama, llama.cpp, LM Studio, vLLM or OpenAI
  itself.

---

## What leaves your Mac

Your voice never leaves the Mac, in either direction, and there's no code path
that sends recorded audio anywhere. Faster-Whisper does the listening here and
Kokoro does the talking here. I checked this by watching the bridge's sockets
through a full round trip, mic in and reply spoken, and the only connections
open were the loopback ones in the table below.

| | Stays on the Mac | Leaves the Mac |
|---|---|---|
| Microphone audio | Yes, transcribed locally | Never |
| Her voice | Yes, synthesised locally | Never |
| Conversation and memory | Yes, saved to disk here | |
| What you said, as text | | Sent to your LLM endpoint |
| Clipboard, when she reads it | | Sent to your LLM endpoint |
| The name of the app you're in | | Sent to your LLM endpoint |
| Screenshots | Only taken when you press the button | Sent to your vision endpoint |

Those three text rows are the honest answer to "is this private". They go
wherever `llm.base_url` points. If that's Ollama on the same Mac, nothing
leaves at all. If it's my Beelink through an SSH tunnel, the text crosses my
own network encrypted and ends up on my own hardware. If it's OpenAI then it
goes to OpenAI, and that's the trade you make by setting it up that way.

Two things are worth knowing specifically.

- **Reading the clipboard sends whatever is on it to the model.** That's how
  "what do you make of this error" works, and it means that tool is only as
  private as the endpoint behind it. You can turn it off with
  `tools.clipboard`.
- **`asr.offline: true`** stops Faster-Whisper checking in with Hugging Face to
  revalidate the cached model every time it loads. None of your data was ever
  in that request, but it was the only outbound connection in the voice path,
  and the voice path is the part I most wanted to be provably local.

The bridge only listens on `127.0.0.1`, so nothing else on your network can
reach it.

## Where to put it

Keep it at `~/marina`. Don't put it in Desktop, Documents or Downloads. macOS
protects those folders with TCC, and an app launched from Finder can't read a
Python venv inside them. It fails in a really annoying way too. Python gets
stuck during its own startup before it can print anything, so the app just
hangs with no error.

If you do move the folder, run `./build-app.sh` again. The app bundle stores the
absolute path so it can find the venv.

## Setup

### 1. Install

```bash
./setup-mac.sh
```

This finds or installs Python 3.12 (macOS comes with 3.9, which is too old for
`onnxruntime`), creates `.venv`, installs the dependencies, downloads the Kokoro
voice model and installs the app's npm packages. It's fine to run it more than
once.

> The `requirements.txt` at the root of the repo is actually GPT-SoVITS's own
> dependency list, with torch, funasr, modelscope and friends. You don't need
> any of it. The Mac side uses `server/requirements-mac.txt`.

### 2. Configure

```bash
cp character_config.example.yaml character_config.yaml
```

The real config is gitignored because it holds your API key. Open it and change
whatever you need.

```yaml
llm:
  base_url: "http://beelink.local:11434/v1"   # your server, leave empty for OpenAI
  api_key: "ollama"                           # ignored locally but must be set
  model: "qwen3:8b"

presets:
  default:
    system_prompt: |
      You are a helpful assistant named Marina.
      You speak like a snarky anime girl.

tts:
  provider: kokoro          # local, or 'sovits' for a remote GPT-SoVITS
  kokoro:
    voice: "af_heart"       # GET /voices lists all 54
```

### 3. Add your avatar

Drop a `.vrm` file at `app/models/model.vrm`, or pick one with the model button
in the app.

**VRoid Studio `.vroid` files won't work.** That's a project file with a
proprietary binary inside, not a 3D model. In VRoid Studio go to Export > VRM
instead. VRM 0.x and VRM 1.0 exports both load fine.

### 4. Run

Build the app once and then open it like anything else.

```bash
./build-app.sh
```

That makes **Marina.app** and copies it to `/Applications`. The app starts the
Python bridge by itself so you don't need a terminal. Drag it to the Dock if you
want to keep it there.

For development you can still run it in two terminals.

```bash
./start-bridge.sh     # the Python side with the mic, Whisper, your LLM and the voice
```

```bash
./start-app.sh        # the avatar
```

---

## Using it

| What | How |
|---|---|
| Type to her | Click the box at the bottom and press Enter |
| Talk to her | The microphone button or **⌘⇧Space**. Press once to start and again to stop |
| Cut her off | Just talk over her, or press **⌘⇧.** |
| Stop her speaking first | Turn off "Let her speak first" in the tray menu |
| Show her your screen | The eye button, or "Look at my screen" in the tray. Type a question first if you want to ask about something specific |
| Move her | Drag the strip along the top of the window |
| Resize her | Drag any edge of the window |
| Hide or show her | The minus button, the tray menu or **⌘⇧H** |
| Forget the conversation | The reset button with the circular arrow |
| Quit | The × button, the tray menu or **⌘⇧Q**, which works from anywhere |

The buttons only show up when you hover, so she looks clean the rest of the
time.

The dot in the bottom left tells you what's happening. Green means ready,
pulsing blue means she's working and red means something broke. The message next
to it says what.

### Microphone permission

Recording happens in the Python process, so macOS asks **the terminal you ran
`./start-bridge.sh` from** for mic access, not the avatar app. Allow it there
the first time. If you dismissed the prompt, go to System Settings > Privacy &
Security > Microphone.

---

## Docs

- **[docs/TTS-ON-MAC.md](docs/TTS-ON-MAC.md)** covers the local voice, blending
  voices, and what it would take to get a truly custom one
- **[docs/LLM-ON-SERVER.md](docs/LLM-ON-SERVER.md)** covers Ollama on the
  Beelink, which model to pick, and why I didn't use the ThinkPad
- **[docs/PIPER-TRAINING.md](docs/PIPER-TRAINING.md)** is about training your
  own voice model and where to actually run the training
- **[docs/GPT-SOVITS.md](docs/GPT-SOVITS.md)** is the voice cloning option, if
  you'd rather move the voice back off the Mac
- **[docs/MAC-PERFORMANCE.md](docs/MAC-PERFORMANCE.md)** has the benchmarks and
  memory numbers I measured on my Mac

---

## Layout

```
character_config.yaml         personality, LLM endpoint, voice
memory.json                   the facts she remembers (readable, editable)
server/
  marina_server.py            local HTTP bridge the app talks to
  main_chat.py                terminal only client (no avatar)
  requirements-mac.txt        slim client deps
  process/
    config.py                 shared config loader
    asr_func/                 Faster-Whisper and the microphone recorder
    asr_func/vad.py           hearing you over her own voice, for barge in
    llm_funcs/llm_scr.py      chat completions client, streaming, tool calls
    text_func/speech.py       splits replies into speech and animation cues,
                              and into speakable chunks while streaming
    idle.py                   when she says something unprompted
    tools/context.py          time, frontmost app, battery
    tools/registry.py         timers, clipboard, links, remembering
    vision/look.py            screenshot to vision model
    memory/store.py           durable facts, deduped and capped
    memory/extract.py         decides what is worth remembering
    tts_func/engine.py        picks the voice backend (kokoro or sovits)
    tts_func/sovits_ping.py   GPT-SoVITS HTTP client
models/kokoro/                local voice model (about 340 MB)
app/
  main.js                     Electron, the transparent always on top window
  preload.js                  IPC bridge
  renderer/app.js             three.js and three-vrm, lip sync, chat UI
  models/model.vrm            your avatar
  test/                       render and transparency smoke tests
```

### Bridge API

The bridge runs at `http://127.0.0.1:8765` and only listens locally.

| Endpoint | What it does |
|---|---|
| `GET /health` | Reports the LLM endpoint, voice backend and model |
| `GET /voices` | Lists the Kokoro voicepacks |
| `POST /chat` | Send `{"text": "..."}` and get back display text, spoken text, cues and a base64 WAV |
| `POST /chat/stream` | The same thing as NDJSON, one event per sentence, each with its own audio |
| `POST /interrupt` | Send `{"chunks": n}` to stop generating and only keep the n sentences you actually heard |
| `GET /barge/listen` | Keeps the mic open while she talks. If you cut in, that becomes the next exchange |
| `GET /idle/listen` | Held open until she has something to say unprompted |
| `POST /idle/mute` | Stops her speaking first |
| `GET /idle/status` | Whether she's due to say something, and what's holding her back |
| `POST /listen/start` | Starts recording |
| `POST /listen/stop` | Stops, transcribes, answers and synthesises |
| `POST /listen/cancel` | Throws the recording away |
| `POST /voice` | Upload an audio file instead of recording |
| `POST /see` | Answers a question about a screenshot |
| `POST /reset` | Forgets the conversation but keeps long term memory |
| `GET /memory` | Everything she remembers |
| `POST /memory` | Teach her a fact directly |
| `DELETE /memory/{id}` | Forget one fact |
| `DELETE /memory` | Wipe long term memory |
| `POST /warmup` | Preloads Whisper and the voice model |

While the bridge is running there are interactive docs at
`http://127.0.0.1:8765/docs`.

---

## Changes from upstream

- Built the VRM desktop frontend. Upstream's `client/` folder only has
  `still_in_development.txt` in it
- Took the hardcoded "refer to the user as senpai" line out of the system prompt
- Added a local Kokoro voice backend so the voice runs on the Mac without a GPU
- Made the voice backend swappable with `tts.provider`, either local Kokoro or
  a remote GPT-SoVITS
- Moved the LLM over to chat completions with a configurable `base_url`, so any
  OpenAI compatible server works (Ollama, llama.cpp, LM Studio, vLLM)
- Made the GPT-SoVITS URL configurable instead of hardcoded to `127.0.0.1:9880`
- Replaced the default `ref_audio_path`, which was an absolute Windows path
- The config now loads relative to the repo and not the current directory.
  Upstream only worked if you were cd'd into the repo root
- Push to talk records for as long as you're talking. Upstream always wrote a
  fixed 60 second buffer, so every clip was padded with silence
- GPT-SoVITS errors are caught properly. On failure it returns JSON with a 400,
  which upstream would happily save to disk as a `.wav`
- LLM failures like a bad key or a rate limit come back as a readable message
  instead of a 500
- Replies are split into spoken text and animation cues, so markdown, emoji and
  roleplay actions get performed or dropped instead of read out loud
- Removed an unused `gradio` import from the LLM module
- Split the requirements. The Mac side needs 8 packages, not the whole
  GPT-SoVITS list

---

## Credits

Built on top of **[rayenfeng/riko_project](https://github.com/rayenfeng/riko_project)**,
which gave me the original terminal voice chat pipeline. Its `client/` folder was
a placeholder and "VRM model frontend" was an unchecked TODO. That frontend and
everything under it is what this repo adds.

**Avatar and rendering**
- [three-vrm](https://github.com/pixiv/three-vrm) for the VRM rig, expressions and spring bones
- [three.js](https://threejs.org) and [Electron](https://www.electronjs.org)
- [VRoid Studio](https://vroid.com/en/studio), where the character was made

**Speech**
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) for speech recognition
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) through
  [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) for the voice
- [soxr](https://pypi.org/project/soxr/) for the pitch shift that keeps timing intact

**Language model**
- [Ollama](https://ollama.com), or any OpenAI compatible endpoint

**Other backends that are wired up and documented**
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) for voice cloning
  ([docs](docs/GPT-SOVITS.md))
- [Piper](https://github.com/OHF-voice/piper1-gpl) for training your own voice
  ([docs](docs/PIPER-TRAINING.md))

MIT licensed.
