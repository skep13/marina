# GPT-SoVITS — running it on your server

GPT-SoVITS is the piece that gives Marina a voice. It is the only heavy model in
this project, and it is the one you said you'd run on your server. Your Mac
never loads it — it just POSTs text and gets a WAV back.

```
  Mac (this repo)                          Your server
  ─────────────────                        ───────────────────────
  mic ──► Faster-Whisper  ──► text
                               │
                               ├──► OpenAI API  ──► reply text
                               │                        │
                               │      POST /tts  ◄──────┘
                               │           │
                               ▼           ▼
                        Electron app   GPT-SoVITS  ──► WAV ──► back to the Mac
```

---

## 1. What the server needs

| | Minimum | Comfortable |
|---|---|---|
| GPU | NVIDIA, 6 GB VRAM | NVIDIA, 12 GB+ |
| CUDA | 12.x | 12.4 / 12.6 |
| RAM | 16 GB | 32 GB |
| Disk | ~25 GB | ~40 GB |
| Python | 3.10 | 3.10 |

**CPU-only works but is not usable for conversation** — expect roughly 10–30×
slower than a GPU, i.e. tens of seconds for one sentence. If your server has no
NVIDIA GPU, tell me and I'll switch the TTS layer to something that runs well on
Apple Silicon instead (Kokoro or Piper), because GPT-SoVITS on CPU will make the
whole thing feel broken.

AMD/ROCm and Intel/XPU builds exist but are much less travelled; assume NVIDIA
unless you enjoy debugging.

---

## 2. Install it (on the server)

```bash
git clone https://github.com/RVC-Boss/GPT-SoVITS
cd GPT-SoVITS

conda create -n GPTSoVits python=3.10
conda activate GPTSoVits

# --device: CU126 for CUDA 12.6, CU128 for 12.8. --download-uvr5 only if you
# plan to strip background music out of your training audio.
bash install.sh --device CU126 --source HF --download-uvr5
```

`install.sh` pulls the pretrained models for you. If you'd rather do it by hand,
they come from [huggingface.co/lj1995/GPT-SoVITS](https://huggingface.co/lj1995/GPT-SoVITS)
and belong in `GPT_SoVITS/pretrained_models/`.

Verify the GPU is actually visible before going further:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## 3. Get a voice

There are two ways, and you should start with the first.

### Zero-shot (works immediately, no training)

Hand it a 3–10 second clean clip of the voice you want plus a transcript of
exactly what's said in it, and it clones the timbre on the fly. That's what
`ref_audio_path` / `prompt_text` in `character_config.yaml` are.

The repo ships `character_files/main_sample.wav` with a matching `prompt_text`,
so you have a working voice from minute one.

Rules that actually matter for the reference clip:

- **3–10 seconds.** Under 3 is unstable, over 10 gets truncated or degrades.
- **No long silences**, no music, no second speaker, no reverb.
- `prompt_text` must match the clip **word for word**. A mismatch is the single
  most common cause of garbled output.
- `prompt_lang` must be the language *spoken in the clip*; `text_lang` is the
  language of what Marina is about to say. They're often the same but not always.

### Fine-tuning (better, costs you an afternoon)

Worth it if you want a specific consistent character voice. Launch the training
WebUI on the server:

```bash
python webui.py
```

Then work top to bottom through the tabs:

1. **UVR5** — strip background music/noise (skip if your audio is already clean).
2. **Slicer** — cut your recordings into short segments.
3. **ASR** — auto-transcribe the segments (Whisper for EN/JA, FunASR for ZH).
4. **Proofread** — fix the transcripts. Do not skip this; garbage in, garbage out.
5. **Formatting** — turn the corrected dataset into training features.
6. **Train GPT**, then **train SoVITS**.

You want roughly **20–60 minutes** of clean single-speaker audio. More than that
has diminishing returns; less than ~10 minutes usually isn't worth it over
zero-shot.

Training produces two weight files. Point the API at them with:

```
GET /set_gpt_weights?weights_path=GPT_weights_v2/yourvoice-e15.ckpt
GET /set_sovits_weights?weights_path=SoVITS_weights_v2/yourvoice_e8_s200.pth
```

---

## 4. Run the API

This is the part Marina talks to.

```bash
conda activate GPTSoVits
python api_v2.py -a 0.0.0.0 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

- `-a 0.0.0.0` binds all interfaces so your Mac can reach it. The default is
  `127.0.0.1`, which would only be reachable from the server itself.
- `-p 9880` is the port. Match it in `character_config.yaml`.

Endpoints it exposes:

| Method | Path | Purpose |
|---|---|---|
| `POST` / `GET` | `/tts` | Synthesize speech |
| `GET` | `/set_gpt_weights?weights_path=…` | Hot-swap the GPT weights |
| `GET` | `/set_sovits_weights?weights_path=…` | Hot-swap the SoVITS weights |
| `GET` | `/set_refer_audio?refer_audio_path=…` | Change the reference clip |
| `GET` | `/control?command=restart` | Restart / exit |

Smoke-test it from the server itself:

```bash
curl -X POST http://127.0.0.1:9880/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "If you hear this, it is set up correctly.",
    "text_lang": "en",
    "ref_audio_path": "/absolute/path/on/the/server/main_sample.wav",
    "prompt_text": "This is a sample voice for you to just get started with.",
    "prompt_lang": "en",
    "media_type": "wav"
  }' --output test.wav
```

> **`ref_audio_path` is resolved on the server, not on your Mac.** This trips
> everyone up. The upstream config shipped with `D:\PyProjects\...`, a Windows
> path, which is why it fails out of the box. Copy your reference WAV onto the
> server and put *that* path in the config.

---

## 5. Point Marina at it

In `character_config.yaml`:

```yaml
sovits_ping_config:
  api_url: "http://YOUR-SERVER:9880/tts"
  text_lang: en
  prompt_lang: en
  ref_audio_path: "/home/you/GPT-SoVITS/refs/main_sample.wav"   # server-side path
  prompt_text: "…exactly what is said in that clip…"
```

Then check the round trip from your Mac:

```bash
source .venv/bin/activate
python -m server.process.tts_func.sovits_ping
```

That writes `output.wav` and prints how long the server took. If it's under
about 2 seconds per sentence, conversation will feel natural.

> **The API has no authentication whatsoever.** Anyone who can reach port
> 9880 can use your GPU and read any file path you pass it. Do not port-forward
> it to the open internet. Put it on Tailscale/WireGuard, or SSH-tunnel it:
> `ssh -N -L 9880:127.0.0.1:9880 you@server`, then leave `api_url` pointing at
> `127.0.0.1:9880`. The tunnel is the option I'd pick.

---

## 6. Tuning knobs

All of these live under `sovits_ping_config` and get forwarded to the API.

| Field | Default | What it does |
|---|---|---|
| `text_split_method` | `cut5` | How long text is chunked. `cut5` splits on punctuation and is the right default for chat. |
| `speed_factor` | `1.0` | Playback speed. `1.1` makes replies feel snappier. |
| `temperature` | `1.0` | Lower = flatter and more stable, higher = more expressive and more likely to glitch. |
| `top_k` | `15` | Sampling breadth. Drop to ~5 if you get occasional garbled words. |
| `batch_size` | `1` | Raise on a big GPU to speed up long replies. |

---

## 7. When it goes wrong

| Symptom | Cause |
|---|---|
| `400` with `ref_audio_path` in the message | The path doesn't exist **on the server**. |
| Speech is garbled or babbles | `prompt_text` doesn't match the reference clip word for word. |
| Wrong accent / wrong language | `text_lang` vs `prompt_lang` mixed up. |
| First request is slow, rest are fast | Normal — models load lazily on the first call. |
| `Could not reach GPT-SoVITS` in the app | API not running, wrong port, or bound to `127.0.0.1` instead of `0.0.0.0`. |
| CUDA OOM | Lower `batch_size`, or shorten the text with a tighter `text_split_method`. |
