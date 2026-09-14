# Marina

Marina is an anime character who lives on your desktop. She sits in a
transparent window that stays on top of everything else, and you can either
talk to her out loud or type. She answers in her own voice, lip syncs while
she does it, and acts out the little stage directions she writes.

It started as a fork of [rayenfeng/riko_project](https://github.com/rayenfeng/riko_project).
That project had the voice pipeline, but the avatar frontend was still an
unchecked TODO, so I built it and split things up so the language model can run
on a different machine.

Everything apart from the language model runs on the Mac. The voice model is
local and uses about 674 MB of RAM.

## What she can do

- Sits on your desktop in a transparent, always-on-top window
- Talk to her or type
- Starts speaking before the whole reply has been generated
- You can cut her off by talking over her
- Sometimes says something without being asked
- Timers, reading the clipboard, opening links, remembering things
- Knows what day and time of day it is
- Can look at your screen when you ask (off by default)
- Lip sync with five mouth shapes
- Hair physics, blinking and eye movement
- `*actions*` in her replies play as animations instead of being read out
- Long-term memory
- Local voice (Kokoro) and speech recognition (Faster-Whisper)
- Works with any OpenAI-compatible model: Ollama, llama.cpp, LM Studio, vLLM
  or OpenAI itself

## What leaves your Mac

Your voice never leaves the Mac, in either direction, and there's no code path
that sends recorded audio anywhere. Faster-Whisper does the listening here and
Kokoro does the talking here. I checked this by watching the bridge's sockets
through a full round trip, mic in and reply spoken, and the only connections
open were loopback ones.

- The clipboard tool sends whatever is on your clipboard to the model, so it's
  only as private as your LLM endpoint. Turn it off with `tools.clipboard`.
- `asr.offline: true` stops Faster-Whisper checking Hugging Face for model
  updates every time it loads.

The bridge only listens on `127.0.0.1`, so nothing else on your network can
reach it.

## Where to put it

Keep it at `~/marina`. Don't put it in Desktop, Documents or Downloads. macOS
protects those folders with TCC, and an app launched from Finder can't read a
Python venv inside them.

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

The `requirements.txt` at the root is GPT-SoVITS's dependency list (torch,
funasr, modelscope and so on). You don't need it on the Mac, which uses
`server/requirements-mac.txt`.

### 2. Configure

```bash
cp character_config.example.yaml character_config.yaml
```

The real config is gitignored because it holds your API key. Open it and change
whatever you need.

```yaml
llm:
  base_url: "http://127.0.0.1:11434/v1"   # your server, leave empty for OpenAI
  api_key: "ollama"                       # ignored locally but must be set
  model: "llama3.2:3b"

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

Add a `.vrm` file at `app/models/model.vrm`, or pick one with the model button
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

## Microphone permission

Recording happens in the Python process, so macOS asks **the terminal you ran
`./start-bridge.sh` from** for mic access, not the avatar app. Allow it there
the first time. If you dismissed the prompt, go to System Settings > Privacy &
Security > Microphone.

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
  test/                       Electron scripts that load the avatar and check it
```

While the bridge is running there are API docs at `http://127.0.0.1:8765/docs`.

## Credits

Built on top of **[rayenfeng/riko_project](https://github.com/rayenfeng/riko_project)**,
which had the original terminal voice chat pipeline. The avatar app and
everything around it is new here.

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

**Optional**
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) as a voice cloning backend

MIT licensed.
