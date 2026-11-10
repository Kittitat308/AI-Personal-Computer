"""Wayu Paxa Thai text-to-speech running locally on ONNX Runtime."""

import json
import sys
import threading
from contextlib import contextmanager

import numpy as np
import onnxruntime as ort

from speech.tts.config import GRAPH_NAMES, MODEL_DIR, TTS_SPEED, TTS_THREADS, TTS_VOICE
from speech.tts.kokoro_thai.g2p import ThaiG2P
from speech.tts.kokoro_thai.onnx_infer import OnnxStudent, count_tokens, synth_phonemes


@contextmanager
def _without_torch():
    """Keep spaCy (used for English words) from importing torch.

    It loads torch whenever it is installed, which costs seconds, and never uses
    it here. If torch is already loaded by the app, nothing changes.
    """
    block = "torch" not in sys.modules
    if block:
        sys.modules["torch"] = None
    try:
        yield
    finally:
        if block and sys.modules.get("torch") is None:
            del sys.modules["torch"]


class WayuTTS:
    def __init__(self, voice: str = TTS_VOICE, speed: float = TTS_SPEED) -> None:
        missing = [
            f"{name}_fp32.onnx"
            for name in GRAPH_NAMES
            if not (MODEL_DIR / f"{name}_fp32.onnx").is_file()
        ]
        if missing:
            raise FileNotFoundError(
                f"ไม่พบไฟล์โมเดลเสียงพูดใน {MODEL_DIR}: " + ", ".join(missing)
            )

        runtime = json.loads((MODEL_DIR / "kokoro-runtime.json").read_text(encoding="utf-8"))
        source = json.loads((MODEL_DIR / "harmonic-source.json").read_text(encoding="utf-8"))
        if voice not in runtime["voices"]:
            raise ValueError(
                f"ไม่พบเสียง {voice!r} เสียงที่มี: " + ", ".join(sorted(runtime["voices"]))
            )

        with _without_torch():
            g2p = ThaiG2P()
            g2p.phonemize("ทดสอบระบบ Hello assistant")

        options = ort.SessionOptions()
        options.intra_op_num_threads = TTS_THREADS
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

        def open_session(name: str) -> ort.InferenceSession:
            return ort.InferenceSession(
                str(MODEL_DIR / f"{name}_fp32.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )

        self.student = OnnxStudent(
            prosody=open_session("prosody"),
            curves=open_session("curves"),
            decoder=open_session("decoder"),
            vocab=runtime["vocab"],
            g2p=g2p,
            source_weight=np.asarray(source["weight"], dtype=np.float32).reshape(1, 9),
            source_bias=np.asarray([source["bias"]], dtype=np.float32),
            window=np.asarray(source["window"], dtype=np.float32),
            precision="fp32",
        )

        details = runtime["voices"][voice]
        styles = np.fromfile(MODEL_DIR / details["fileName"], dtype="<f4")
        self.styles = styles.reshape(int(details["rows"]), 1, 256)
        self.speed = float(details.get("speed", 1.0)) * speed
        # The Thai frontend keeps shared state, so one request runs at a time.
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> np.ndarray:
        """Float32 mono audio at 24 kHz, empty when the text has nothing to say."""
        with self._lock:
            phonemes = self.student.g2p.phonemize(text)
            token_count = count_tokens(self.student, phonemes)
            if token_count == 0:
                return np.zeros(0, dtype=np.float32)
            style = self.styles[min(max(token_count - 1, 0), len(self.styles) - 1)]
            return synth_phonemes(self.student, phonemes, style, speed=self.speed)
