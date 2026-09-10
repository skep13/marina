"""Text-to-speech dispatch.

Two backends, chosen by `tts.provider` in character_config.yaml:

  kokoro  - runs locally on the Mac. 82M params, ~4x realtime on an M2,
            ~670 MB resident. Fixed voicepacks; cannot clone a voice.
  sovits  - GPT-SoVITS over HTTP, wherever you run it. Clones a voice from
            a short reference clip, but wants an NVIDIA GPU.

Both return WAV bytes, so the rest of the pipeline doesn't care which is in use.
"""
import io
import threading

from process.config import load_config, resolve

_config = load_config()
_tts = _config.get("tts") or {}

PROVIDER = (_tts.get("provider") or "kokoro").strip().lower()


class TTSError(RuntimeError):
    pass


_kokoro = None
_kokoro_lock = threading.Lock()


def _kokoro_cfg():
    return _tts.get("kokoro") or {}


def _load_kokoro():
    """Loaded lazily and only once — it costs ~0.8 s and ~500 MB."""
    global _kokoro
    with _kokoro_lock:
        if _kokoro is not None:
            return _kokoro

        try:
            from kokoro_onnx import Kokoro
        except ImportError as e:
            raise TTSError(
                "kokoro-onnx isn't installed. Run ./setup-mac.sh, or switch "
                "tts.provider to 'sovits'."
            ) from e

        cfg = _kokoro_cfg()
        model = resolve(cfg.get("model_path", "models/kokoro/kokoro-v1.0.onnx"))
        voices = resolve(cfg.get("voices_path", "models/kokoro/voices-v1.0.bin"))

        for path, what in ((model, "model"), (voices, "voices")):
            if not path.exists():
                raise TTSError(
                    f"Kokoro {what} file missing at {path}. "
                    "Run ./download-kokoro.sh to fetch it."
                )

        print("Loading Kokoro...", flush=True)
        _kokoro = Kokoro(str(model), str(voices))
        print("Kokoro ready.", flush=True)
        return _kokoro


def _resolve_voice(kokoro, cfg):
    """Either a voicepack name, or a weighted blend of several.

    Kokoro voices are style vectors, so a weighted average of two packs is
    itself a valid voice. That's the closest thing to a custom voice this
    backend offers — it can't clone a specific person.
    """
    blend = cfg.get("blend")
    if not blend:
        return cfg.get("voice", "af_heart")

    total = sum(float(w) for w in blend.values())
    if total <= 0:
        raise TTSError("tts.kokoro.blend weights must add up to more than zero.")

    mixed = None
    for name, weight in blend.items():
        part = kokoro.get_voice_style(name) * (float(weight) / total)
        mixed = part if mixed is None else mixed + part
    return mixed


def _pitch_shift(audio, semitones):
    """Raise or lower pitch without changing duration.

    Resampling alone changes pitch and duration together, so the generation
    speed is pre-divided by the same ratio and the resample puts the duration
    back. This shifts the formants along with the pitch, which is exactly what
    makes a voice read as smaller and younger rather than as a slowed-down
    adult — the opposite of what a formant-preserving shifter would do, and
    the right choice here.
    """
    if abs(semitones) < 0.01:
        return audio

    ratio = 2.0 ** (semitones / 12.0)
    try:
        import soxr
        return soxr.resample(audio, ratio, 1.0)
    except ImportError:
        import numpy as np
        n = int(len(audio) / ratio)
        idx = np.linspace(0, len(audio) - 1, n)
        return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def _kokoro_gen(text):
    import soundfile as sf

    cfg = _kokoro_cfg()
    kokoro = _load_kokoro()

    voice = _resolve_voice(kokoro, cfg)
    semitones = float(cfg.get("pitch", 0.0))
    ratio = 2.0 ** (semitones / 12.0)

    speed = float(cfg.get("speed", 1.0)) / ratio

    try:
        audio, sample_rate, timings = kokoro.create_timed(
            text,
            voice=voice,
            speed=speed,
            lang=cfg.get("lang", "en-us"),
        )
        audio = _pitch_shift(audio, semitones)
    except Exception as e:
        available = ""
        try:
            available = ", ".join(sorted(kokoro.get_voices())[:8]) + ", ..."
        except Exception:
            pass
        label = voice if isinstance(voice, str) else "blend"
        raise TTSError(
            f"Kokoro failed on voice '{label}': {e}"
            + (f" Available voices: {available}" if available else "")
        ) from e

    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue(), visemes_from(timings, 1.0 / ratio)


_VISEME_BY_PHONEME = {
    "ɑ": "aa", "a": "aa", "ʌ": "aa", "æ": "aa", "ɐ": "aa", "ɒ": "aa",
    "i": "ee", "ɪ": "ee", "e": "ee", "ɛ": "ee", "eɪ": "ee", "ᵻ": "ee",
    "ə": "ih", "ɚ": "ih", "ɜ": "ih", "ɝ": "ih", "ɹ": "ih",
    "ɔ": "oh", "o": "oh", "oʊ": "oh", "aʊ": "oh", "ɔɪ": "oh", "aɪ": "oh",
    "u": "ou", "ʊ": "ou", "w": "ou", "uː": "ou",
}

_CLOSED = set("mbp")


def visemes_from(timings, scale=1.0):
    """Turn phoneme timings into a viseme track the renderer can play.

    Returns [{t, v, w}] - time in seconds, viseme name, and how open. An empty
    list is a valid answer: the model may not expose durations, and the
    renderer still has its analyser to fall back on.
    """
    track = []
    for timing in timings or []:
        raw = (timing.phoneme or "").strip()
        if not raw:
            continue
        base = raw[0]
        if base in _CLOSED:
            track.append({"t": round(timing.start * scale, 4), "v": "aa", "w": 0.0})
            continue
        viseme = _VISEME_BY_PHONEME.get(raw[:2]) or _VISEME_BY_PHONEME.get(base)
        if not viseme:
            continue
        track.append({
            "t": round(timing.start * scale, 4),
            "v": viseme,
            "w": round(min(1.0, max(0.25, (timing.end - timing.start) * 12)), 3),
        })
    return track


def kokoro_voices():
    """Every voicepack name, for the /voices endpoint."""
    try:
        return sorted(_load_kokoro().get_voices())
    except TTSError:
        return []


def describe():
    if PROVIDER == "kokoro":
        cfg = _kokoro_cfg()
        if cfg.get("blend"):
            mix = "+".join(f"{n}:{w}" for n, w in cfg["blend"].items())
            pitch = float(cfg.get('pitch', 0.0))
            suffix = f" · pitch{pitch:+.1f}st" if pitch else ""
            return f"kokoro (local) · blend={mix}{suffix}"
        pitch = float(cfg.get('pitch', 0.0))
        suffix = f" · pitch{pitch:+.1f}st" if pitch else ""
        return f"kokoro (local) · voice={cfg.get('voice', 'af_heart')}{suffix}"
    if PROVIDER == "sovits":
        from process.tts_func.sovits_ping import API_URL

        return f"gpt-sovits · {API_URL}"
    return PROVIDER


def synthesize(text):
    """Return (WAV bytes, viseme track) for `text`, or raise TTSError.

    The track is empty for engines that cannot report phoneme timings; the
    renderer falls back to analysing the audio in that case.
    """
    if not text or not text.strip():
        raise TTSError("Refusing to synthesize empty text.")

    if PROVIDER == "kokoro":
        return _kokoro_gen(text)

    if PROVIDER == "sovits":
        from process.tts_func.sovits_ping import SovitsError, sovits_gen_bytes

        try:
            return sovits_gen_bytes(text), []
        except SovitsError as e:
            raise TTSError(str(e)) from e

    raise TTSError(f"Unknown tts.provider '{PROVIDER}'. Use 'kokoro' or 'sovits'.")


def warmup():
    """Preload whichever backend is local, so the first reply isn't slow.

    Loading the model is not enough. ONNX builds its execution plan on the
    first inference, and that first call runs at roughly half the speed of
    every one after it — measured at 1.6x realtime against 3.3x warm. With
    replies streamed a sentence at a time, that penalty lands squarely on the
    opening segment, which is the one thing the user is actually waiting for.
    So burn a throwaway utterance here instead.
    """
    if PROVIDER == "kokoro":
        _load_kokoro()
        try:
            _kokoro_gen("Ready.")
        except Exception as e:
            print(f"[tts] warmup inference failed: {e}", flush=True)
