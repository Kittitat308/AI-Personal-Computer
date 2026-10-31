from __future__ import annotations

import re
import threading
import time

import numpy as np
import sherpa_onnx

from speech.stt.config import (
    DECODER_PATH,
    ENCODER_PATH,
    FEATURE_DIM,
    JOINER_PATH,
    NUM_THREADS,
    SAMPLE_RATE,
    TOKENS_PATH,
)


class STTService:
    """In-process Thai speech recognition powered by Sherpa-ONNX Zipformer."""

    def __init__(self) -> None:
        self.recognizer: sherpa_onnx.OfflineRecognizer | None = None
        self._cancel_requested = threading.Event()
        self._decode_lock = threading.Lock()

    def start(self) -> None:
        if self.recognizer is not None:
            return

        self._validate_files()
        print("กำลังโหลด Sherpa-ONNX Zipformer Thai INT8 ด้วย CPU...")
        started = time.perf_counter()
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(ENCODER_PATH),
            decoder=str(DECODER_PATH),
            joiner=str(JOINER_PATH),
            tokens=str(TOKENS_PATH),
            num_threads=NUM_THREADS,
            sample_rate=SAMPLE_RATE,
            feature_dim=FEATURE_DIM,
            decoding_method="greedy_search",
            provider="cpu",
        )
        print(f"โหลดโมเดลสำเร็จ: {time.perf_counter() - started:.2f} วินาที")
        print("STT พร้อมใช้งาน")

    def prepare_transcription(self) -> None:
        self._cancel_requested.clear()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def cancel_current(self) -> None:
        """Discard the active result; native decoding is short and finishes in place."""
        self.request_cancel()

    def close(self) -> None:
        self.request_cancel()
        with self._decode_lock:
            self.recognizer = None

    def transcribe_audio(self, audio: np.ndarray) -> str:
        samples = np.ascontiguousarray(
            np.asarray(audio, dtype=np.float32).reshape(-1)
        )
        if samples.size == 0 or self._cancel_requested.is_set():
            return ""
        if self.recognizer is None:
            raise RuntimeError("STT ยังไม่ได้โหลดโมเดล")

        print("กำลังแปลงเสียงเป็นข้อความ...")
        started = time.perf_counter()
        with self._decode_lock:
            if self._cancel_requested.is_set() or self.recognizer is None:
                return ""
            stream = self.recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            self.recognizer.decode_stream(stream)
            text = stream.result.text.strip()

        if self._cancel_requested.is_set():
            return ""
        print(f"STT: {time.perf_counter() - started:.2f} วินาที")
        return text

    @staticmethod
    def is_shutdown_command(text: str) -> bool:
        normalized = re.sub(r"[\s.!?…。、，！？]+", "", text).casefold()
        return "ปิดระบบ" in normalized

    @staticmethod
    def _validate_files() -> None:
        missing = [
            path
            for path in (ENCODER_PATH, DECODER_PATH, JOINER_PATH, TOKENS_PATH)
            if not path.is_file()
        ]
        if missing:
            paths = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"ไม่พบไฟล์ STT: {paths}")
