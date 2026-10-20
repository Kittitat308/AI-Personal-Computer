import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "").strip()
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "").strip()
AZURE_SPEECH_VOICE = os.getenv(
    "AZURE_SPEECH_VOICE",
    "th-TH-NiwatNeural",
).strip()
AZURE_SPEECH_RATE = os.getenv("AZURE_SPEECH_RATE", "+15%").strip()

REQUEST_TIMEOUT_SECONDS = 8.0
OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"


def validate_tts_settings() -> None:
    missing = []

    if not AZURE_SPEECH_KEY:
        missing.append("AZURE_SPEECH_KEY")
    if not AZURE_SPEECH_REGION:
        missing.append("AZURE_SPEECH_REGION")

    if missing:
        raise RuntimeError(
            "ยังไม่ได้ตั้งค่า Azure TTS: " + ", ".join(missing)
        )
