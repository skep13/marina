"""Non-blocking microphone recorder used by the desktop app.

The app sends "start", you talk, the app sends "stop", and we hand back a
WAV path. Recording happens in this process (not in Electron) so the only
microphone permission macOS ever asks about is the one for the terminal /
Python that runs the bridge.
"""
import queue
import tempfile
import threading
from pathlib import Path

SAMPLERATE = 16000  # Whisper resamples to 16k anyway; recording there saves work.
CHANNELS = 1


class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._stream = None
        self._frames = None

    @property
    def is_recording(self):
        return self._stream is not None

    def start(self):
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return False

            self._frames = queue.Queue()

            def callback(indata, _frames, _time, status):
                if status:
                    print(f"[mic] {status}", flush=True)
                self._frames.put(indata.copy())

            self._stream = sd.InputStream(
                samplerate=SAMPLERATE,
                channels=CHANNELS,
                dtype="float32",
                callback=callback,
            )
            self._stream.start()
            return True

    def stop(self):
        """Stop recording and return a path to the WAV, or None if empty."""
        import numpy as np
        import soundfile as sf

        with self._lock:
            if self._stream is None:
                return None

            self._stream.stop()
            self._stream.close()
            self._stream = None

            chunks = []
            while not self._frames.empty():
                chunks.append(self._frames.get())
            self._frames = None

        if not chunks:
            return None

        audio = np.concatenate(chunks)
        # Under ~0.25s is almost certainly a mis-click, not speech.
        if len(audio) < SAMPLERATE * 0.25:
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, audio, SAMPLERATE)
        return Path(tmp.name)

    def cancel(self):
        path = self.stop()
        if path:
            path.unlink(missing_ok=True)
