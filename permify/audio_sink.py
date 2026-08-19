from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections import deque
from typing import Optional

SAMPLE_RATE = 44100
CHANNELS = 2
BYTES_PER_SAMPLE = 2  # int16
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE


def bytes_to_ms(nbytes: int) -> int:
    return int(nbytes * 1000 / BYTES_PER_SECOND)


def ms_to_bytes(ms: int) -> int:
    return int(ms * BYTES_PER_SECOND / 1000)


class FFTAnalyzer:
    """Turns the PCM going to the speakers into visualizer band levels.

    The audio thread feeds every consumed byte through push(); the render
    loop calls bands() whenever it likes. All numpy work happens in bands()
    so the audio path stays as cheap as a bytearray append.
    """

    def __init__(self, n_bands: int = 32, window: int = 2048,
                 rate: int = SAMPLE_RATE):
        self.n_bands = n_bands
        self.window = window
        self.rate = rate
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._levels = [0.0] * n_bands
        self._edges = None
        self._hann = None

    def push(self, pcm: bytes) -> None:
        try:
            with self._lock:
                self._buf += pcm
                cap = self.window * 4  # stereo s16 frames
                if len(self._buf) > cap:
                    del self._buf[: len(self._buf) - cap]
        except Exception:
            pass

    def _prep(self, np) -> None:
        freqs = np.fft.rfftfreq(self.window, 1.0 / self.rate)
        self._edges = []
        for i in range(self.n_bands):
            f0 = 38.0 * (15000.0 / 38.0) ** (i / self.n_bands)
            f1 = 38.0 * (15000.0 / 38.0) ** ((i + 1) / self.n_bands)
            idx = np.nonzero((freqs >= f0) & (freqs < f1))[0]
            if not idx.size:
                idx = np.array([min(i + 1, len(freqs) - 1)])
            self._edges.append(idx)
        self._hann = np.hanning(self.window)

    def bands(self) -> list:
        """32 smoothed magnitudes 0..1, bass on the left, highs on the right."""
        try:
            import numpy as np
        except Exception:
            return list(self._levels)
        if self._edges is None:
            self._prep(np)
        with self._lock:
            raw = bytes(self._buf)
        raw = raw[: len(raw) // 4 * 4]
        if len(raw) < self.window * 4:
            return list(self._levels)
        try:
            a = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).mean(axis=1)
            a = a[-self.window:] * self._hann
            spec = np.abs(np.fft.rfft(a))
            out = []
            for idx in self._edges:
                v = float(np.sqrt(spec[idx].mean()))
                out.append(min(1.0, (v / 2600.0) ** 0.65))  # compress + gain
            sm = [max(out[i], max(out[max(0, i - 1): i + 2]) * 0.75)
                  for i in range(len(out))]
            self._levels = [max(n, lv * 0.80)
                            for n, lv in zip(sm, self._levels)]
        except Exception:
            pass
        return list(self._levels)


class PCMRing:
    """Thread-safe producer/consumer ring of raw PCM chunks."""

    def __init__(self, cap_bytes: int = 2_500_000):  # ~14 s of audio
        self._dq = deque()
        self._size = 0
        self._cap = cap_bytes
        self._cond = threading.Condition()
        self.closed = False
        self.analyzer: Optional[FFTAnalyzer] = None  # visualizer tap

    def push(self, data: bytes) -> bool:
        """Block while full; returns False if closed while waiting."""
        with self._cond:
            while self._size + len(data) > self._cap and not self.closed:
                self._cond.wait(0.2)
            if self.closed:
                return False
            self._dq.append(data)
            self._size += len(data)
            self._cond.notify_all()
            return True

    def take(self, nbytes: int) -> bytes:
        """Non-blocking: returns up to nbytes worth of samples."""
        with self._cond:
            out = bytearray()
            while self._dq and nbytes > 0:
                head = self._dq[0]
                if len(head) <= nbytes:
                    out += head
                    self._dq.popleft()
                    self._size -= len(head)
                    nbytes -= len(head)
                else:
                    out += head[:nbytes]
                    self._dq[0] = head[nbytes:]
                    self._size -= nbytes
                    nbytes = 0
            self._cond.notify_all()
            data = bytes(out)
        an = self.analyzer
        if an is not None and data:  # feed the visualizer outside the lock
            try:
                an.push(data)
            except Exception:
                pass
        return data

    def clear(self) -> None:
        with self._cond:
            self._dq.clear()
            self._size = 0
            self._cond.notify_all()

    def buffered(self) -> int:
        with self._cond:
            return self._size

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()


class BaseSink:
    kind = "base"

    def __init__(self, ring: PCMRing):
        self.ring = ring
        self.volume = 0.6
        self.paused = True
        self._played_bytes = 0
        self._played_lock = threading.Lock()

    # -- to subclass -----------------------------------------------------
    def start(self) -> None: ...
    def close(self) -> None: ...

    # -- shared ----------------------------------------------------------
    def set_paused(self, flag: bool) -> None:
        self.paused = flag

    def set_volume(self, v01: float) -> None:
        self.volume = max(0.0, min(1.0, v01))

    def reset_played(self) -> None:
        with self._played_lock:
            self._played_bytes = 0

    def played_ms(self) -> int:
        with self._played_lock:
            return bytes_to_ms(self._played_bytes)


class SoundDeviceSink(BaseSink):
    kind = "sounddevice"

    def __init__(self, ring: PCMRing):
        super().__init__(ring)
        self._sd = None
        self._stream = None

    def start(self) -> None:
        if self._stream is not None:
            return
        import numpy as np
        import sounddevice as sd

        def callback(outdata, frames, time_info, status):  # noqa: ARG001
            out = np.frombuffer(outdata, dtype=np.int16)
            nbytes = out.nbytes
            if self.paused:
                out[:] = 0
                return
            data = self.ring.take(nbytes)
            with self._played_lock:
                self._played_bytes += len(data)
            if len(data) < nbytes:
                data = data + b"\x00" * (nbytes - len(data))
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            samples *= self.volume
            out[:] = np.clip(samples, -32768, 32767).astype(np.int16)

        self._stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=2048,
            callback=callback,
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


class ExternalSink(BaseSink):
    """Pipes PCM into an external player (ffplay / sox / paplay / aplay).

    Slower to seek (player buffers) but works where sounddevice can't.
    """

    kind = "external"
    _COMMANDS = [
        ("ffplay", ["ffplay", "-loglevel", "quiet", "-nodisp", "-autoexit",
                    "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "2", "-i", "pipe:0"]),
        ("play",   ["play", "-q", "-t", "raw", "-r", str(SAMPLE_RATE),
                    "-e", "signed", "-b", "16", "-c", "2", "-"]),
        ("paplay", ["paplay", "--raw", "--format=s16le",
                    f"--rate={SAMPLE_RATE}", "--channels=2"]),
        ("aplay",  ["aplay", "-q", "-f", "cd", "-"]),
    ]

    def __init__(self, ring: PCMRing):
        super().__init__(ring)
        self.cmd = self._find_command()
        self._proc = None
        self._thread = None
        self._run = False

    @classmethod
    def available(cls) -> bool:
        return cls._find_command() is not None

    @classmethod
    def _find_command(cls):
        for name, cmd in cls._COMMANDS:
            if shutil.which(name):
                return cmd
        return None

    def start(self) -> None:
        if self._proc is not None or self.cmd is None:
            return
        self._proc = subprocess.Popen(
            self.cmd + ["-"] if self.cmd[0] == "paplay" else self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._run = True
        self._thread = threading.Thread(target=self._writer, daemon=True, name="sink-writer")
        self._thread.start()

    def _writer(self) -> None:
        silence = b"\x00" * 4096
        while self._run and self._proc and self._proc.poll() is None:
            if self.paused:
                chunk = silence
                real = 0
            else:
                chunk = self.ring.take(4096)
                real = len(chunk)
                if not chunk:
                    chunk = silence
                elif len(chunk) < 4096:
                    chunk += silence[: 4096 - len(chunk)]
            try:
                self._proc.stdin.write(chunk)
                self._proc.stdin.flush()
                if real:
                    with self._played_lock:
                        self._played_bytes += real
            except (BrokenPipeError, ValueError, OSError):
                break
            else:
                # crude pacing: pipe back-pressure does most of the work,
                # but keep us honest if the player's buffer is huge.
                time.sleep(0.005)

    def close(self) -> None:
        self._run = False
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None


def pick_sink(ring: PCMRing, prefer: str = "auto") -> BaseSink:
    """First try sounddevice; if PortAudio is missing fall back to ffplay & co."""
    errors = []
    if prefer in ("auto", "sounddevice"):
        sink = SoundDeviceSink(ring)
        try:
            sink.start()
            sink.close()  # just probing; player restarts it
            return SoundDeviceSink(ring)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"sounddevice: {exc}")
    if prefer in ("auto", "external") and ExternalSink.available():
        return ExternalSink(ring)
    detail = "; ".join(errors) or "no external player (ffplay/sox/paplay/aplay) found"
    raise RuntimeError(f"no usable audio output ({detail})")
