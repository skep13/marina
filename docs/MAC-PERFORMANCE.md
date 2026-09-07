# Can this Mac run it?

**Short answer: yes, comfortably — because the heavy model isn't running here.**

Measured on the actual machine: Apple M2, 8 cores, 8 GB RAM, macOS 26.6.2.

---

## What runs where

| Stage | Where | Cost to your Mac |
|---|---|---|
| Microphone capture | Mac | negligible |
| **Faster-Whisper** (speech → text) | **Mac, CPU** | 547 MB, ~1 s per utterance |
| **LLM** (text → reply) | **Your server** | network only |
| **Kokoro** (reply → speech) | **Mac, CPU** | 674 MB, ~4× realtime |
| VRM avatar + lip sync | Mac, GPU | ~870 MB, low GPU load |

The reason this fits on 8 GB is that the LLM runs elsewhere and the voice model
is small. Kokoro is 82M parameters — three orders of magnitude smaller than the
model generating the words.

---

## Measured: speech recognition

Transcribing an 8.52 s clip, CPU, `int8` quantization:

| Model | Transcribe time | Speed | Verdict |
|---|---|---|---|
| `tiny.en` | 1.50 s | 5.7× realtime | Fast, noticeably worse accuracy |
| **`base.en`** | **0.98 s** | **8.7× realtime** | **Configured default — best balance** |
| `small.en` | 2.58 s | 3.3× realtime | Better accuracy, still fine for chat |

`base.en` transcribes a typical 5-second sentence in well under a second. You can
move to `small.en` in `character_config.yaml` if it mishears you; you'll feel
about 1.5 s of extra delay per turn, which is tolerable.

**Why CPU and not the GPU?** Faster-Whisper runs on CTranslate2, which has CUDA
and CPU backends but no Metal backend. There is no GPU option for it on Apple
Silicon. The M2's CPU is fast enough that this doesn't matter.

First run downloads the model from Hugging Face (~150 MB for `base.en`) and takes
a few seconds longer; after that it's cached in `~/.cache/huggingface`.

---

## Measured: speech synthesis

Kokoro, ONNX, CPU:

| | |
|---|---|
| Model load | 0.81 s (lazy, once) |
| Generation | **~4× realtime** — 7.08 s of audio in 1.79 s |
| Resident | 674 MB |
| Output | 24 kHz mono 16-bit WAV |

---

## Measured: memory

| Process | RSS |
|---|---|
| Python bridge, `base.en` loaded and used | **547 MB** |
| … plus Kokoro loaded and used | **674 MB** |
| Electron main | 195 MB |
| Electron GPU process | 242 MB |
| Electron renderer (three.js + your 17 MB VRM) | 382 MB |
| Electron utility | 50 MB |
| **Total** | **~1.5 GB** |

On 8 GB that leaves plenty for a browser and an editor. It is not free, though —
if you routinely run 30 Chrome tabs plus Docker you'll feel it. Two ways to cut
it if needed:

- Set `asr.model: tiny.en` — saves roughly 150 MB.
- Don't call `/warmup`; Whisper then loads only the first time you actually
  speak, and text-only chat never pays for it at all.

---

## Latency budget, end to end

For a spoken turn, measured or estimated per stage:

| Stage | Time |
|---|---|
| Whisper transcription (measured) | ~1 s |
| LLM round trip on your server | ~1–3 s, depends on model size |
| Kokoro synthesis (measured) | ~1.8 s for a 7 s reply |
| **Total before Marina starts talking** | **~3–5 s** |

Typing instead of speaking removes the first second.

The one number I can't measure from here is your server's LLM latency. Once
Ollama is up on the Beelink:

```bash
curl -s http://beelink.local:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"say hi"}]}'
```

If that returns in under ~2 s, conversation will feel natural. If it's slow, the
fix is a smaller model on that box — not anything on this Mac.

---

## Screen vision

Asking her to look at your screen swaps Ollama from the chat model to
`qwen2.5vl:3b` and back. Measured: **~17–20 s** per look on this Mac, most of
which is the model swap, not the inference — 8 GB can't hold both at once.

On the Beelink with 32 GB both models stay resident and this drops to a few
seconds. `vision.max_edge` (default 1024) caps the screenshot's long edge;
vision models charge tokens by pixel area, and a raw Retina screenshot is
~6,500 tokens, which overflows a 4,096 context on its own.

## The graphics side

Your model is 46,656 triangles across 20 materials with MToon (toon) shading.
That is small. The M2's GPU renders it at display refresh rate without effort;
the renderer is capped at 2× pixel ratio so a 420×680 window draws 840×1360.

Idle GPU cost is low but not zero — it's a continuously animating 3D scene, so
it will use some battery. If you're on the move, hide the window with **⌘⇧H**;
hidden windows stop rendering.

---

## What would *not* work on this Mac

To be explicit about the thing you correctly avoided:

- **GPT-SoVITS locally.** It's a PyTorch model built around CUDA. On an M2 you'd
  be on CPU or partial MPS, and you'd wait tens of seconds per sentence. The
  upstream `requirements.txt` (torch, funasr, modelscope, pyopenjtalk, …) is
  ~6 GB installed. This is why `server/requirements-mac.txt` exists instead —
  it's 8 packages, no torch.
- **A local LLM of useful size.** 8 GB total means roughly a 7B model at 4-bit
  with nothing else running. Doable, but it would compete with everything else
  for RAM and be slower than the API.

Both of those are exactly what you've already offloaded, which is why this works.
