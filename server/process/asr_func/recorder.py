"""Non-blocking microphone recorder used by the desktop app.

The app sends "start", you talk, the app sends "stop", and we hand back a
WAV path. Recording happens in this process (not in Electron) so the only
microphone permission macOS ever asks about is the one for the terminal /
Python that runs the bridge.

It also runs in a second mode, `monitor`, which is how she can be interrupted:
the microphone is armed while she is talking and a voice activity detector
watches it, so cutting her off is just talking over her rather than reaching
for a button. See `vad.py` for why that is harder than it sounds.
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
        """Begin capturing. Pass a `VAD` to also emit speech start/end events."""
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
        """Run the detector over whatever whole frames have arrived.

        Called on the audio thread, so it does no allocation beyond a slice and
        never blocks — anything slow here shows up as dropped input.
        """
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
        """Stop recording and return a path to the WAV, or None if empty.

        `from_onset` trims everything before the detector heard speech, which
        is what a barge-in wants — the buffer starts when she started talking,
        and all of that is her voice, not yours.
        """
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
