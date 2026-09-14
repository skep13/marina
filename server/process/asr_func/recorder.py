"""Microphone recorder for the bridge.

Pass a VAD to start() to get speech start/end events, used for barge-in.
"""
import queue
import tempfile
import threading
from pathlib import Path

SAMPLERATE = 16000
CHANNELS = 1

PREROLL_SECONDS = 0.35


class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._stream = None
        self._frames = None
        self._vad = None
        self._pending = None
        self._samples_seen = 0
        self._onset_sample = None
        self.events = None

    @property
    def is_recording(self):
        return self._stream is not None

    @property
    def is_monitoring(self):
        return self._stream is not None and self._vad is not None

    def start(self, vad=None):
        import numpy as np
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return False

            self._frames = queue.Queue()
            self._vad = vad
            self._pending = np.zeros(0, dtype="float32")
            self._samples_seen = 0
            self._onset_sample = None
            self.events = queue.Queue() if vad is not None else None

            def callback(indata, _frames, _time, status):
                if status:
                    print(f"[mic] {status}", flush=True)
                block = indata.copy()
                self._frames.put(block)
                if self._vad is not None:
                    self._analyse(block.reshape(-1))

            self._stream = sd.InputStream(
                samplerate=SAMPLERATE,
                channels=CHANNELS,
                dtype="float32",
                callback=callback,
            )
            self._stream.start()
            return True

    def _analyse(self, mono):
        import numpy as np

        self._pending = np.concatenate((self._pending, mono))
        size = self._vad.frame
        while len(self._pending) >= size:
            frame, self._pending = self._pending[:size], self._pending[size:]
            self._samples_seen += size
            event = self._vad.update(frame)
            if event == "start" and self._onset_sample is None:
                self._onset_sample = self._samples_seen - size
            if event:
                self.events.put(event)

    def stop(self, from_onset=False):
        """Return the WAV path, or None. `from_onset` drops audio from before
        the VAD heard speech."""
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
            onset = self._onset_sample
            self._vad = None
            self._onset_sample = None

        if not chunks:
            return None

        audio = np.concatenate(chunks)
        if from_onset and onset is not None:
            start = max(0, int(onset - PREROLL_SECONDS * SAMPLERATE))
            audio = audio[start:]

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
