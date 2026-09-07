# Training a custom Piper voice

The payoff: a ~60 MB ONNX model that runs faster than realtime on your Mac's
CPU, in a couple hundred MB of RAM, forever. It's the only route to a genuinely
custom voice that respects the 8 GB budget.

The catch is the training itself.

---

## The honest problem: you have no training GPU

Piper is a VITS model trained with PyTorch. Training wants CUDA.

| Machine | GPU | Can it train? |
|---|---|---|
| MacBook M2 | Apple GPU (MPS) | No — the training stack assumes CUDA |
| Beelink SER9 | Radeon 890M (RDNA 3.5) | Not realistically — see below |
| ThinkPad T470 | Intel HD 620 | No |

For scale: the docs note `--data.batch_size 32` fits a **24 GB** card (3090/4090),
and a 12 GB card needs the batch size halved with roughly double the time per
epoch. Fine-tuning is ~1000 epochs. On CPU that's weeks, not hours.

**About ROCm on the Beelink:** the Radeon 890M is gfx1150, which sits outside
AMD's officially supported list. People do get PyTorch+ROCm running on Strix
Point iGPUs with `HSA_OVERRIDE_GFX_VERSION`, but you'd be debugging the toolchain
rather than training a voice. Not where I'd spend the weekend.

### So train it somewhere else

**Google Colab (free)** — a T4 with 16 GB. Use `--data.batch_size 16`. Free
sessions get cut off after a few hours, so write checkpoints to Google Drive and
resume with `--ckpt_path`. Slow, but costs nothing.

**Rent a GPU (recommended)** — [vast.ai](https://vast.ai) or RunPod, an RTX 3090
or 4090 for roughly $0.20–0.40/hour. A fine-tune on ~30 minutes of audio is a
day or so of GPU time, so call it **$5–10 total**. You do this once. Given the
time you'd otherwise sink into fighting ROCm, this is the cheap option.

Either way the commands below are identical — only `--data.batch_size` changes.

---

## Step 1: Record the dataset

**This is the part that decides whether the voice is good.** The training is
mechanical; the audio is not.

Targets for fine-tuning (not from scratch):

| | |
|---|---|
| Total audio | 30–60 minutes |
| Utterances | ~1000–1300 short phrases |
| Format | mono WAV, 22050 Hz |
| Clip length | 2–10 seconds each |

Rules that matter more than they sound:

- **One speaker, one microphone, one room, one session** if you can. Consistency
  beats quality — a mediocre mic used consistently beats a great mic across three
  different rooms.
- **No background noise, no music, no reverb.** Piper will faithfully learn your
  refrigerator hum.
- **The transcript must match the audio exactly**, including stumbles you left
  in. Mismatched text is the single biggest cause of a bad voice.
- **Read varied sentences** — questions, statements, exclamations. If you only
  read flat declaratives, that's the only prosody it learns.
- Leave a little silence at the start and end of each clip, but trim long gaps.

[Piper Recording Studio](https://github.com/rhasspy/piper-recording-studio) is a
browser tool that prompts you with sentences and records clips in the right
format. It saves a lot of tedium versus doing it by hand in Audacity.

> If you're cloning someone else's voice rather than your own, get their consent
> first. That's not a legal opinion, it's just the line.

### Layout

```
mydataset/
├── metadata.csv
└── wavs/
    ├── utt1.wav
    ├── utt2.wav
    └── ...
```

`metadata.csv` is pipe-delimited, filename then text:

```csv
utt1.wav|Hey, I'm not doing that for you.
utt2.wav|Fine. But you owe me one.
utt3.wav|Did you seriously just ask me that?
```

---

## Step 2: Install the trainer

The original `rhasspy/piper` went read-only in October 2025 and the license moved
to GPL-3.0. Active development is now **OHF-Voice/piper1-gpl** — use that.

On the training box (Linux, CUDA):

```bash
sudo apt-get install build-essential cmake ninja-build

git clone https://github.com/OHF-voice/piper1-gpl.git
cd piper1-gpl
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[train]'
./build_monotonic_align.sh
python3 setup.py build_ext --inplace
```

---

## Step 3: Get a base checkpoint

Do **not** train from scratch. From scratch wants ~13,000 utterances and ~2000
epochs; fine-tuning wants ~1300 and ~1000, and sounds better at your data size.

Grab a checkpoint from
[huggingface.co/datasets/rhasspy/piper-checkpoints](https://huggingface.co/datasets/rhasspy/piper-checkpoints).

Pick one that **matches your target sample rate** — `medium` quality voices are
22050 Hz, which is what you want. A same-language, same-gender starting voice
converges faster, but any English medium checkpoint works.

---

## Step 4: Train

```bash
python3 -m piper.train fit \
  --data.voice_name "marina" \
  --data.csv_path /path/to/mydataset/metadata.csv \
  --data.audio_dir /path/to/mydataset/wavs/ \
  --model.sample_rate 22050 \
  --data.espeak_voice "en-us" \
  --data.cache_dir /path/to/cache/ \
  --data.config_path /path/to/write/config.json \
  --data.batch_size 32 \
  --ckpt_path /path/to/base-checkpoint.ckpt
```

- `--data.batch_size` — **32** on a 24 GB card, **16** on a 12–16 GB card
  (including Colab's T4). Too high is an out-of-memory crash, not a slow run.
- `--ckpt_path` — the base checkpoint from step 3. This is what makes it a
  fine-tune rather than starting cold, and the docs call it highly recommended.
- `--data.espeak_voice` — the espeak-ng voice for your language's phonemisation.

**Resuming.** The same `--ckpt_path` flag takes your *own* checkpoints, so a
Colab session that gets cut off resumes by pointing it at the last checkpoint
instead of the base one. Write checkpoints somewhere persistent (Drive, or a
volume on a rented box) before you start, not after you lose four hours.

Listen to samples as it goes. Fine-tuning often sounds good well before the
epoch count you planned — there's no prize for finishing.

---

## Step 5: Export to ONNX

```bash
python3 -m piper.train.export_onnx \
  --checkpoint /path/to/your-final.ckpt \
  --output-file marina.onnx
```

You need **two** files to run the voice: `marina.onnx` and the `config.json` that
training wrote (`--data.config_path`). Convention is to name them as a pair:

```
en_US-marina-medium.onnx
en_US-marina-medium.onnx.json
```

Copy both back to the Mac, into `models/piper/`.

---

## Step 6: Use it in Marina

The runtime is a clean install on your Mac — `piper-tts` ships a native arm64
wheel and reuses the `onnxruntime` that's already there:

```bash
source .venv/bin/activate
pip install piper-tts
```

There isn't a `piper` backend in `server/process/tts_func/engine.py` yet — adding
one is a single function that takes text and returns WAV bytes, the same shape as
the `kokoro` and `sovits` backends. Ask and I'll wire it up; it's a small change,
and it makes sense to do it once you actually have a `.onnx` in hand.

---

## Is it worth it?

Honestly, decide after you've lived with Kokoro for a week.

Piper is worth it if you specifically want *a particular voice* — yours, or one
you've designed. It is not worth it as a quality upgrade: Kokoro's voicepacks are
generally cleaner than a first-attempt Piper fine-tune on 30 minutes of
home-recorded audio, and blending gets you a distinctive voice for free.

The cost is roughly: an afternoon recording, a day of GPU time, $5–10, and a
couple of false starts. The payoff is permanent and nearly free to run.
