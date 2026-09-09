"""Speech-to-text with Faster-Whisper.

Two entry points:
  transcribe_file()      - used by the desktop app (audio arrives over HTTP)
  record_and_transcribe() - used by the terminal client (push to talk)
"""
import os

from faster_whisper import WhisperModel

from process.config import load_config


def build_model():
    """Load Whisper, preferring the copy already on disk.

    faster-whisper resolves the model through the Hugging Face hub, which
    contacts huggingface.co on every single load to check the cached copy is
    current — even when it is. Nothing of yours is sent, but it is the only
    outbound connection anywhere in the voice path, and voice is the part of
    this that most deserves to be provably local.

    So: try the cache first and go to the network only when there is nothing
    cached to use, which is the first run and no other time.
    """
    cfg = load_config().get("asr", {})
    name = cfg.get("model", "base.en")
    kwargs = {
        "device": cfg.get("device", "cpu"),
        "compute_type": cfg.get("compute_type", "int8"),
    }

    if cfg.get("offline", True):
        try:
            return WhisperModel(name, local_files_only=True, **kwargs)
        except Exception:                               # noqa: BLE001
            print(f"[asr] {name} isn't cached yet; downloading it once.",
                  flush=True)

    return WhisperModel(name, **kwargs)


def transcribe_file(model, path):
    segments, _ = model.transcribe(str(path), vad_filter=True)
    return " ".join(segment.text for segment in segments).strip()


def record_and_transcribe(model, output_file="recording.wav", samplerate=44100):
    """Terminal push-to-talk. Records until you press ENTER again."""
    import queue

    import sounddevice as sd
    import soundfile as sf

    if os.path.exists(output_file):
        os.remove(output_file)

    print("Press ENTER to start recording...")
    input()
    print("Recording... press ENTER to stop")

    # The upstream version pre-allocated a fixed 60s buffer and always wrote
    # all 60 seconds to disk, padding every clip with silence. Stream instead
    # so the clip is exactly as long as you spoke.
    frames = queue.Queue()

    def callback(indata, _frames, _time, status):
        if status:
            print(status)
        frames.put(indata.copy())

    with sd.InputStream(samplerate=samplerate, channels=1, callback=callback):
        input()

    print("Saving audio...")
    chunks = []
    while not frames.empty():
        chunks.append(frames.get())

    if not chunks:
        print("Nothing recorded.")
        return ""

    import numpy as np

    sf.write(output_file, np.concatenate(chunks), samplerate)

    print("Transcribing...")
    transcription = transcribe_file(model, output_file)
    print(f"Transcription: {transcription}")
    return transcription


if __name__ == "__main__":
    print(f"Got: '{record_and_transcribe(build_model())}'")
