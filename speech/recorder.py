import threading

import numpy as np
import sounddevice as sd


SAMPLE_RATE = 16_000
CHANNELS = 1


class ManualRecorder:
    """Records one push-to-talk segment without running VAD."""

    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self.recording:
            return
        with self._lock:
            self._chunks.clear()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._on_audio,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            if not self._chunks:
                return np.empty(0, dtype=np.float32)
            audio = np.concatenate(self._chunks).astype(np.float32)
            self._chunks.clear()
            return audio

    def close(self) -> None:
        self.stop()

    def _on_audio(self, input_data, frames, time_info, status) -> None:
        del frames, time_info
        if status:
            print(f"MIC WARNING: {status}")
        with self._lock:
            self._chunks.append(input_data[:, 0].copy())
