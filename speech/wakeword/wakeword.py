from collections.abc import Callable
from threading import Event
import threading
import time

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

from speech.wakeword.config import (
    EMBEDDING_MODEL_PATH,
    END_SILENCE_SECONDS,
    MAX_COMMAND_SECONDS,
    MELSPECTROGRAM_MODEL_PATH,
    RMS_THRESHOLD,
    SAMPLE_RATE,
    START_SPEECH_TIMEOUT_SECONDS,
    WAKEWORD_FRAME_SAMPLES,
    WAKEWORD_MODEL_PATH,
    WAKEWORD_NAME,
    WAKEWORD_THRESHOLD,
)


class WakeWordService:
    """Listen locally for the configured wake word, then capture one command."""

    def __init__(self) -> None:
        self._cancel = Event()
        self._model: Model | None = None

    def start(self) -> None:
        for path in (
            WAKEWORD_MODEL_PATH,
            MELSPECTROGRAM_MODEL_PATH,
            EMBEDDING_MODEL_PATH,
        ):
            if not path.is_file():
                raise FileNotFoundError(f"ไม่พบโมเดล OpenWakeWord: {path}")

        print(f"กำลังโหลดโมเดลคำปลุก {WAKEWORD_NAME}...")
        self._model = Model(
            wakeword_models=[str(WAKEWORD_MODEL_PATH)],
            inference_framework="onnx",
            melspec_model_path=str(MELSPECTROGRAM_MODEL_PATH),
            embedding_model_path=str(EMBEDDING_MODEL_PATH),
            ncpu=1,
        )
        self._model.predict(np.zeros(WAKEWORD_FRAME_SAMPLES, dtype=np.int16))
        self._model.reset()
        print("ระบบคำปลุกพร้อมใช้งาน")

    def cancel(self) -> None:
        self._cancel.set()

    def close(self) -> None:
        self.cancel()
        self._model = None

    def listen_for_command(self) -> np.ndarray:
        """Detect the wake word and capture the command on one mic stream."""
        if self._model is None:
            raise RuntimeError("ระบบคำปลุกยังไม่ได้เริ่มทำงาน")

        self._cancel.clear()
        self._model.reset()
        chunk_seconds = WAKEWORD_FRAME_SAMPLES / SAMPLE_RATE
        silence_limit = max(1, round(END_SILENCE_SECONDS / chunk_seconds))
        start_limit = max(1, round(START_SPEECH_TIMEOUT_SECONDS / chunk_seconds))
        command_limit = max(1, round(MAX_COMMAND_SECONDS / chunk_seconds))
        recorded: list[np.ndarray] = []
        speech_started = False
        silence_frames = 0
        waiting_frames = 0
        command_frames = 0

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=WAKEWORD_FRAME_SAMPLES,
        ) as stream:
            while not self._cancel.is_set():
                frame, _overflowed = stream.read(WAKEWORD_FRAME_SAMPLES)
                mono_int16 = frame[:, 0].copy()
                scores = self._model.predict(mono_int16)
                if scores and max(scores.values()) >= WAKEWORD_THRESHOLD:
                    self._model.reset()
                    print("ตรวจพบคำปลุก กำลังฟังคำสั่งต่อทันที...")
                    break
            else:
                return np.empty(0, dtype=np.float32)

            while not self._cancel.is_set():
                frame, _overflowed = stream.read(WAKEWORD_FRAME_SAMPLES)
                mono = frame[:, 0].astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(np.square(mono))))

                if not speech_started:
                    waiting_frames += 1
                    if rms >= RMS_THRESHOLD:
                        speech_started = True
                        recorded.append(mono)
                    elif waiting_frames >= start_limit:
                        break
                    continue

                recorded.append(mono)
                command_frames += 1
                if rms >= RMS_THRESHOLD:
                    silence_frames = 0
                else:
                    silence_frames += 1
                    if silence_frames >= silence_limit:
                        break
                if command_frames >= command_limit:
                    break

        if not recorded or self._cancel.is_set():
            return np.empty(0, dtype=np.float32)
        return np.concatenate(recorded).astype(np.float32, copy=False)


class WakeWordListener:
    """Run wake-word capture in a stoppable background thread."""

    def __init__(
        self,
        service: WakeWordService,
        on_command: Callable[[np.ndarray], None],
        can_listen: Callable[[], bool],
        on_error: Callable[[Exception], None],
    ) -> None:
        self.service = service
        self.on_command = on_command
        self.can_listen = can_listen
        self.on_error = on_error
        self._stop = Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="alexa-wake-word",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.service.cancel()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.can_listen():
                time.sleep(0.05)
                continue
            try:
                audio = self.service.listen_for_command()
            except Exception as error:
                if not self._stop.is_set():
                    self.on_error(error)
                return
            if self._stop.is_set():
                return
            if audio.size and self.can_listen():
                self.on_command(audio)
                time.sleep(0.05)
