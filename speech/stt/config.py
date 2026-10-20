import os
from pathlib import Path


STT_DIR = Path(__file__).resolve().parent
WHISPER_DIR = STT_DIR / "whisper"
MODEL_PATH = WHISPER_DIR / "ggml-thonburian-distilled-small-q8_0.bin"
WARMUP_AUDIO_PATH = STT_DIR / "warmup.wav"
STT_RETRY_AUDIO_PATH = STT_DIR / "stt_retry.wav"

WHISPER_EXECUTABLE = WHISPER_DIR / (
    "whisper-server.exe" if os.name == "nt" else "whisper-server"
)

HOST = "127.0.0.1"
PORT = 8081
THREADS = 4
LANGUAGE = "th"
SERVER_START_TIMEOUT_SECONDS = 60.0
INFERENCE_TIMEOUT_SECONDS = 10.0
WARMUP_TIMEOUT_SECONDS = 30.0
CANCEL_REQUEST_TIMEOUT_SECONDS = 1.0
CANCEL_WAIT_TIMEOUT_SECONDS = 3.0

SAMPLE_RATE = 16_000
CHANNELS = 1
