# Voice on the Mac

You want the voice model on the Mac and the LLM on your server. That works, and
it's what's configured. But there's one constraint worth being blunt about
before you plan around it.

## The constraint

**Voice *cloning* and 8 GB of RAM don't really fit together.**

The Mac is already carrying:

| | |
|---|---|
| Faster-Whisper (`base.en`) | 547 MB |
| Electron + three.js + your VRM | ~870 MB |
| macOS itself | ~2–3 GB |
| **Left over** | **~3.5 GB** |

Against that, here's what the cloning-capable models want:

| Model | Clones a voice? | RAM | Fits? |
|---|---|---|---|
| **Kokoro** (installed) | ✗ fixed voicepacks | **674 MB** | ✅ comfortably |
| Piper | ✗ (train one instead) | ~150 MB | ✅ comfortably |
| F5-TTS (MLX) | ✅ zero-shot | ~1.5–2 GB | ⚠️ tight |
| Chatterbox | ✅ zero-shot, best quality | **~6 GB** | ❌ no |
| GPT-SoVITS | ✅ zero-shot + fine-tune | needs torch (~6 GB installed), wants CUDA | ❌ no |

So: local voice on the Mac — yes, easily. Local *cloned* voice on the Mac —
only by giving something up.

---

## What's configured: Kokoro

82M parameters, ONNX, ~340 MB on disk. Measured on your M2:

| | |
|---|---|
| Load time | 0.81 s (once, lazily) |
| Generation | **~4× realtime** — a 7 s reply in 1.8 s |
| Resident | 674 MB |
| Voices | 54 |

It has no cloning, but 54 voicepacks is a lot of range: `af_*` American female,
`bf_*` British female, `jf_*` Japanese female, and `am_`/`bm_`/`jm_` male
equivalents. `GET http://127.0.0.1:8765/voices` lists them all while the bridge
is running.

```yaml
tts:
  provider: kokoro
  kokoro:
    voice: "af_heart"
    speed: 1.0
```

### Pitch

Kokoro exposes speed but not pitch, and anime-girl voices sit higher than any
of its packs. `pitch` shifts in semitones:

```yaml
tts:
  kokoro:
    pitch: 3.0     # +2 to +4 is the useful range; past +5 it's a chipmunk
```

Duration is preserved: generation is slowed by the same ratio the resample
speeds it back up by, so `speed` still means what it says.

It shifts formants along with pitch, which is *wanted* here — that's what makes
a voice read as smaller and younger, rather than an adult played fast. A
formant-preserving shifter would sound more natural but less anime.

### Voice blending

Kokoro voices are style vectors, which means a weighted average of two packs is
itself a valid voice. It isn't cloning, but it does get you a voice that isn't
just "the default one":

```yaml
tts:
  kokoro:
    blend:
      jf_alpha: 0.6      # Japanese-female timbre
      af_heart: 0.4      # American-female clarity
```

Weights are normalised, so they don't need to sum to 1. This overrides `voice`.

---

## The ceiling

Pitch and blending change the *timbre*, and that gets you most of the way. What
they cannot fix is **prosody** — Kokoro is an 82M-parameter model, and its
sentence melody is flat. That flatness is what still reads as "AI", and no
amount of pitch shifting removes it.

Getting past it means a bigger model that clones real delivery, not just timbre:

- **F5-TTS via MLX on this Mac** (~1.5–2 GB) — clones from a short reference
  clip, so you could feed it a few seconds of a voice you like. Tight on 8 GB
  but workable.
- **Chatterbox or GPT-SoVITS on the Beelink** — better again, and the Mac's RAM
  stops being the constraint once the LLM moves off it.

Both are a step change rather than a tweak. Say the word and I'll wire one up.

## If you want a genuinely custom voice

Three routes, in the order I'd try them.

### 1. Train a Piper voice — best fit for your hardware

Piper runs a *trained* model rather than cloning at inference time. The trained
voice is ~60 MB and runs faster than realtime on CPU with almost no RAM. You
train once on a rented or free cloud GPU, then run it on the Mac forever.

- You need ~30–60 minutes of clean single-speaker audio.
- Training is a one-off afternoon, not a live dependency.
- Result: a permanent custom voice that costs the Mac almost nothing.

This is the option that actually respects the 8 GB budget. Full walkthrough in
[PIPER-TRAINING.md](PIPER-TRAINING.md) — including the awkward part, which is
that none of your three machines can do the training.

### 2. F5-TTS via MLX — zero-shot cloning, tight fit

`f5-tts-mlx` runs on Apple Silicon through Metal and clones from a short
reference clip. At ~1.5–2 GB it will fit in the leftover budget, but not with
much room, and it's several times slower than Kokoro. Worth trying if you want
cloning *today* without training anything.

### 3. Put the cloning model on the Beelink after all

The SER9 has 32 GB. GPT-SoVITS or Chatterbox would fit there without argument.
This contradicts "TTS on the Mac", but it's the only way to get
best-in-class cloning in this setup — and switching is one line:

```yaml
tts:
  provider: sovits          # instead of kokoro
sovits_ping_config:
  api_url: "http://beelink.local:9880/tts"
```

The GPT-SoVITS backend is already written and wired; see
[GPT-SOVITS.md](GPT-SOVITS.md). The catch is that it really wants an NVIDIA GPU,
and the SER9's is a Radeon 890M — so expect CPU-speed inference there, which
may be too slow for conversation. Chatterbox would likely be the better fit on
that box.

---

## Switching backends

The TTS layer dispatches on one config key, and both backends return WAV bytes,
so nothing downstream changes:

```yaml
tts:
  provider: kokoro    # or: sovits
```

Adding a third backend means one function in
`server/process/tts_func/engine.py` that takes text and returns WAV bytes.
