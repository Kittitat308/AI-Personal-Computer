import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

MODEL_DIR = Path(__file__).resolve().parent / "model"
GRAPH_NAMES = ("prosody", "curves", "decoder")

# Voice names are the voice-*.bin files in model/ (for example m_young_clear).
TTS_VOICE = os.getenv("TTS_VOICE", "").strip() or "m_young_clear"
# Multiplies the speaking speed of the voice (1.0 keeps the voice's own pace).
TTS_SPEED = float(os.getenv("TTS_SPEED", "").strip() or 1.0)
TTS_THREADS = int(os.getenv("TTS_THREADS", "").strip() or min(8, os.cpu_count() or 1))

SAMPLE_RATE = 24_000
# Long replies are spoken in pieces so the first piece plays while the next one
# is still being generated.
MAX_CHUNK_CHARACTERS = 80
MIN_CHUNK_CHARACTERS = 20
