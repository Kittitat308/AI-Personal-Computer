import threading
from collections import deque
from collections.abc import Callable

import numpy as np
import sounddevice as sd
import torch
from silero_vad import load_silero_vad


SAMPLE_RATE = 16_000
CHANNELS = 1
VAD_CHUNK_SIZE = 512
VAD_THRESHOLD = 0.90
RMS_THRESHOLD = 0.010
VAD_SILENCE_SECONDS = 1.5
VAD_PRE_SPEECH_SECONDS = 0.3
MAX_RECORD_SECONDS = 10.0


class VoiceListener:
    def __init__(
        self,
        on_utterance: Callable[[np.ndarray], None],
        can_listen: Callable[[], bool],
        on_error: Callable[[Exception], None],
    ):
        self.on_utterance = on_utterance
        self.can_listen = can_listen
        self.on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._model = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="always-on-vad",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None

    def _run(self) -> None:
        try:
            if self._model is None:
                self._model = load_silero_vad()
            self._capture_loop()
        except Exception as error:
            self.on_error(error)

    def _capture_loop(self) -> None:
        chunk_seconds = VAD_CHUNK_SIZE / SAMPLE_RATE
        pre_chunks = max(1, int(VAD_PRE_SPEECH_SECONDS / chunk_seconds))
        silence_required = max(1, int(VAD_SILENCE_SECONDS / chunk_seconds))
        max_chunks = max(1, int(MAX_RECORD_SECONDS / chunk_seconds))
        pre_buffer = deque(maxlen=pre_chunks)
        recorded: list[np.ndarray] = []
        speech_started = False
        silence_chunks = 0
        recorded_after_start = 0
        self._model.reset_states()

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=VAD_CHUNK_SIZE,
        ) as stream:
            while not self._stop.is_set():
                audio_chunk, _ = stream.read(VAD_CHUNK_SIZE)
                mono = audio_chunk[:, 0].copy()

                if not self.can_listen():
                    pre_buffer.clear()
                    recorded.clear()
                    speech_started = False
                    silence_chunks = 0
                    recorded_after_start = 0
                    self._model.reset_states()
                    continue

                rms = float(np.sqrt(np.mean(np.square(mono))))
                with torch.no_grad():
                    probability = float(
                        self._model(torch.from_numpy(mono).float(), SAMPLE_RATE).item()
                    )
                is_speech = probability >= VAD_THRESHOLD

                if not speech_started:
                    pre_buffer.append(mono)
                    if is_speech and rms >= RMS_THRESHOLD:
                        speech_started = True
                        recorded.extend(pre_buffer)
                        pre_buffer.clear()
                    continue

                recorded.append(mono)
                recorded_after_start += 1
                silence_chunks = 0 if is_speech else silence_chunks + 1

                if silence_chunks >= silence_required or recorded_after_start >= max_chunks:
                    utterance = np.concatenate(recorded).astype(np.float32)
                    recorded = []
                    speech_started = False
                    silence_chunks = 0
                    recorded_after_start = 0
                    pre_buffer.clear()
                    self._model.reset_states()
                    self.on_utterance(utterance)


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
