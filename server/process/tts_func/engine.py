"""Text-to-speech. `tts.provider` picks kokoro (local) or sovits (HTTP)."""
import io
import re
import threading

from process.config import load_config, resolve

_config = load_config()
_tts = _config.get("tts") or {}

PROVIDER = (_tts.get("provider") or "kokoro").strip().lower()


class TTSError(RuntimeError):
    pass


_kokoro = None
_kokoro_lock = threading.Lock()


def _preset_tts():
    """The current personality's own voice settings, if it has any:
    tts: {voice, speed, pitch, rvc: false} in its preset."""
    from process import config
    return (config.presets().get(config.preset()) or {}).get("tts") or {}


def _kokoro_cfg():
    over = {k: v for k, v in _preset_tts().items() if k in ("voice", "blend", "speed", "pitch")}
    base = dict(_tts.get("kokoro") or {})
    if "voice" in over:
        base.pop("blend", None)
    return {**base, **over}


def _load_kokoro():
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
                    "Run scripts/download-kokoro.sh to fetch it."
                )

        print("Loading Kokoro...", flush=True)
        _kokoro = Kokoro(str(model), str(voices))
        print("Kokoro ready.", flush=True)
        return _kokoro


def _resolve_voice(kokoro, cfg):
    """A voice name, or a weighted average of several voice style vectors."""
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


_SENTENCE = re.compile(r"[^.!?…]+(?:[.!?…]+|$)")


def _tone(sentence):
    """How a sentence should sound from its punctuation: (speed, semitones).
    Kokoro on its own reads everything in one tone, so exclamations come out
    quicker and higher, questions lift, trailing "..." slows and drops."""
    s = sentence.strip()
    if s.endswith(("...", "…")):
        return 0.9, -0.6
    if "!" in s[-3:]:
        return 1.08, 0.9 + (0.4 if s.count("!") > 1 or s.isupper() else 0.0)
    if s.endswith("?"):
        return 1.03, 0.5
    return 1.0, 0.0


def _kokoro_gen(text):
    import numpy as np
    import soundfile as sf

    cfg = _kokoro_cfg()
    kokoro = _load_kokoro()

    voice = _resolve_voice(kokoro, cfg)
    base_semitones = float(cfg.get("pitch", 0.0))

    from process import mood
    base_speed = float(cfg.get("speed", 1.0)) * mood.voice_speed()
    expressive = cfg.get("expressive", True) is not False
    parts = [p for p in _SENTENCE.findall(text) if p.strip()] if expressive else [text]
    parts = parts or [text]

    chunks, visemes, offset, sample_rate = [], [], 0.0, 24000
    for part in parts:
        speed_mul, lift = _tone(part) if expressive else (1.0, 0.0)
        semitones = base_semitones + lift
        ratio = 2.0 ** (semitones / 12.0)
        try:
            audio, sample_rate, timings = kokoro.create_timed(
                part.strip(),
                voice=voice,
                speed=base_speed * speed_mul / ratio,
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
        for v in visemes_from(timings, 1.0 / ratio):
            visemes.append({**v, "t": round(v["t"] + offset, 4)})
        chunks.append(np.asarray(audio, dtype=np.float32))
        offset += len(audio) / sample_rate

    buf = io.BytesIO()
    sf.write(buf, np.concatenate(chunks), sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue(), visemes


_VISEME_BY_PHONEME = {
    "ɑ": "aa", "a": "aa", "ʌ": "aa", "æ": "aa", "ɐ": "aa", "ɒ": "aa",
    "i": "ee", "ɪ": "ee", "e": "ee", "ɛ": "ee", "eɪ": "ee", "ᵻ": "ee",
    "ə": "ih", "ɚ": "ih", "ɜ": "ih", "ɝ": "ih", "ɹ": "ih",
    "ɔ": "oh", "o": "oh", "oʊ": "oh", "aʊ": "oh", "ɔɪ": "oh", "aɪ": "oh",
    "u": "ou", "ʊ": "ou", "w": "ou", "uː": "ou",
}

_CLOSED = set("mbp")


def visemes_from(timings, scale=1.0):
    """Phoneme timings to [{t, v, w}]: time, viseme, weight."""
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
    try:
        return sorted(_load_kokoro().get_voices())
    except TTSError:
        return []


def describe():
    if PROVIDER == "kokoro":
        cfg = _kokoro_cfg()
        if cfg.get("blend"):
            mix = "+".join(f"{n}:{w}" for n, w in cfg["blend"].items())
            voice = f"blend={mix}"
        else:
            voice = f"voice={cfg.get('voice', 'af_heart')}"
        pitch = float(cfg.get("pitch", 0.0))
        suffix = f" · pitch{pitch:+.1f}st" if pitch else ""
        rvc = " · rvc" if (_tts.get("rvc") or {}).get("url") else ""
        return f"kokoro (local) · {voice}{suffix}{rvc}"
    if PROVIDER == "sovits":
        from process.tts_func.sovits_ping import API_URL

        return f"gpt-sovits · {API_URL}"
    return PROVIDER


def _rvc(wav):
    """Kokoro's speech in her RVC voice (appliance/rvc), when `tts.rvc.url`
    is set. Same length, so the lip sync timings still fit. Anything wrong
    and she just speaks in plain Kokoro."""
    url = str((_tts.get("rvc") or {}).get("url") or "").rstrip("/")
    if not url or _preset_tts().get("rvc") is False:
        return wav
    import urllib.request
    try:
        req = urllib.request.Request(url + "/convert", data=wav, method="POST",
                                     headers={"Content-Type": "audio/wav"})
        with urllib.request.urlopen(req, timeout=float((_tts.get("rvc") or {}).get("timeout", 15))) as r:
            out = r.read()
        return out if out[:4] == b"RIFF" else wav
    except Exception as e:
        print(f"[tts] rvc unavailable, plain kokoro: {e}", flush=True)
        return wav


# Kokoro spells little sounds out letter by letter: "mm" comes out as "M M",
# "mhm" and "mm-hm" as "em em hum". Swap them for words it says as sounds
# ("uh-huh", "hmm"). Checked by transcribing what Kokoro made, 2026-11-27.
_FILLERS = [
    (re.compile(r"\b(?:m+-?h+m+|m+h+m*|uh-?huh)\b", re.I), "uh-huh"),
    (re.compile(r"\b(?:m{2,}|h+m+)\b", re.I), "hmm"),
]


def spoken_fillers(text):
    for rx, word in _FILLERS:
        text = rx.sub(lambda m, w=word: w.capitalize() if m.group(0)[0].isupper() else w, text)
    return text


def synthesize(text):
    """Return (wav_bytes, visemes). visemes is empty for sovits."""
    if not text or not text.strip():
        raise TTSError("Refusing to synthesize empty text.")
    text = spoken_fillers(text)

    if PROVIDER == "kokoro":
        wav, visemes = _kokoro_gen(text)
        return _rvc(wav), visemes

    if PROVIDER == "sovits":
        from process.tts_func.sovits_ping import SovitsError, sovits_gen_bytes

        try:
            return sovits_gen_bytes(text), []
        except SovitsError as e:
            raise TTSError(str(e)) from e

    raise TTSError(f"Unknown tts.provider '{PROVIDER}'. Use 'kokoro' or 'sovits'.")


def warmup():
    if PROVIDER == "kokoro":
        _load_kokoro()
        try:
            _kokoro_gen("Ready.")
        except Exception as e:
            print(f"[tts] warmup inference failed: {e}", flush=True)
