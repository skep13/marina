# Stardance submission — copy/paste answers

Not part of the app. Copy the fields below into the form.

---

## What are you building?

Marina is a desktop companion, not a chat window. She's a VRM avatar that lives
on your screen in a transparent, always-on-top window — you talk to her by voice
or by typing, and she talks back with a synthesised voice, lip-syncs to it, and
acts out what she writes.

She runs on a MacBook Air with 8 GB of RAM. That constraint drove most of the
design: speech recognition, voice synthesis and rendering are all local and
deliberately small, and only the language model sits behind an
OpenAI-compatible endpoint, so it can be Ollama on the same machine, a server on
your LAN, or a hosted API without changing anything else.

The parts I'm most pleased with:

- **She performs, rather than narrates.** When the model writes `*tilts head*`,
  that's stripped out of the speech and played as an animation instead of being
  read aloud as "asterisk tilts head asterisk". 19 cues — nod, shake, shrug,
  eyeroll, wink, sigh — each timed to fire at the point in the audio where it
  was written, not dumped at the start.
- **Lip sync is a vowel model, not a jaw hinge.** Loudness in decibels sets how
  far the mouth opens; the balance between the first two formant bands picks
  between five visemes, so the mouth changes *shape*. Sibilants get detected and
  damped, otherwise every "s" reads as a shout.
- **Her hair moves with real physics.** The VRM already carries spring-bone
  simulation; it just has nothing to react to when she stands still. Rather than
  animate strands, a simulated breeze leans the gravity direction each joint
  falls toward, so the solver does the work and long strands swing more than
  short ones for free.
- **She remembers you between conversations,** and has a life of her own between
  them — an ongoing thread picked from the date, so she's still stuck on the
  same edit all day and has moved on by tomorrow.
- **She's a friend, not an assistant.** No "how can I help you today?". She's
  allowed to be busy, unimpressed, or to just not help.

Packaged as a real `.app` that starts its own Python backend, so it opens from
the Dock like anything else.

## Started before June 1 2026 / previously shipped

**Please check with an organiser rather than taking my word for it.**

This is built on top of [rayenfeng/riko_project](https://github.com/rayenfeng/riko_project),
an existing MIT-licensed project that predates this work. I did not start from
an empty folder.

What I inherited from it: a terminal-only Python script that recorded audio,
sent it to Whisper, then to OpenAI, then to a GPT-SoVITS server — roughly 200
lines across four files.

What is new here: the entire avatar frontend (upstream's `client/` directory
contains a single file, `still_in_development.txt`, and "VRM model frontend" is
an unchecked TODO in its README), the animation and lip-sync systems, the memory
layer, the local TTS backend, the macOS app packaging, and the test suite. The
upstream commit is still the root of this repo's history, so the diff is
inspectable.

I've flagged it because "new work on an existing base" is a judgement call for
you, not for me.

---

## Demo URL

https://skep13.github.io/marina/

A demo page with a render of the avatar, three audio samples of her voice, and
the measured numbers. Worth also recording thirty seconds of the real app — a
transparent window lip-syncing on a desktop is the one thing a static page
cannot show.

---

## GitHub URL

https://github.com/skep13/marina

---

## References

Everything this is built on.

**Base project**
- [rayenfeng/riko_project](https://github.com/rayenfeng/riko_project) — the
  original voice-chat pipeline this extends (MIT)

**Avatar and rendering**
- [pixiv/three-vrm](https://github.com/pixiv/three-vrm) — VRM loading, humanoid
  rig, expressions, spring bones
- [three.js](https://threejs.org) — rendering
- [Electron](https://www.electronjs.org) — the transparent desktop window
- [VRoid Studio](https://vroid.com/en/studio) — where the character was made

**Speech**
- [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) — speech
  recognition, CTranslate2 backend
- [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — the voice model
- [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) — the
  ONNX runtime wrapper actually used here
- [soxr](https://pypi.org/project/soxr/) — resampling for the pitch shift

**Language model**
- [Ollama](https://ollama.com) — local model serving
- [llama3.2](https://ollama.com/library/llama3.2) — the model currently used

**Supported but not required**
- [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) — alternative
  cloning TTS backend, wired and documented
- [OHF-voice/piper1-gpl](https://github.com/OHF-voice/piper1-gpl) — training a
  custom voice, documented in `docs/PIPER-TRAINING.md`
- [Qwen2.5-VL](https://ollama.com/library/qwen2.5vl) — screen vision, built then
  disabled (it evicts the chat model on 8 GB)
