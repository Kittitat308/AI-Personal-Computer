import tempfile
import time
import unicodedata
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

from speech.stt import STTService
from speech.stt.config import CANCEL_REQUEST_TIMEOUT_SECONDS, SAMPLE_RATE


class GUISTTService(STTService):
    """Adds waveform transcription without changing the existing STT service."""

    _NO_SPEECH_TRANSCRIPTS = {
        "ขอโทษค่ะคุณพูดว่าอะไรนะ",
        "ขอโทษค่ะคุณพูดว่าอะไรนะคะ",
        "ขอโทษค่ะคุณพูว่าอะไรนะ",
        "ขอโทษค่ะคุณพูว่าอะไรนะคะ",
        "ขอโทษครับคุณพูดว่าอะไรนะ",
        "ขอโทษครับคุณพูดว่าอะไรนะครับ",
    }

    @staticmethod
    def _normalized_transcript(text: str) -> str:
        return "".join(
            character
            for character in text.casefold()
            if not character.isspace()
            and unicodedata.category(character)[0] not in {"P", "S"}
        )

    @classmethod
    def _is_no_speech_transcript(cls, text: str) -> bool:
        normalized = cls._normalized_transcript(text)
        return normalized in {
            cls._normalized_transcript(phrase)
            for phrase in cls._NO_SPEECH_TRANSCRIPTS
        }

    def transcribe_audio(self, audio: np.ndarray) -> str:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return ""
        temporary = tempfile.NamedTemporaryFile(
            prefix="ai_pc_stt_",
            suffix=".wav",
            delete=False,
        )
        temporary.close()
        audio_path = Path(temporary.name)
        sf.write(audio_path, samples, SAMPLE_RATE, subtype="PCM_16")
        try:
            text = self._transcribe(audio_path)
            return "" if self._is_no_speech_transcript(text) else text
        finally:
            audio_path.unlink(missing_ok=True)

    def close(self) -> None:
        owned_server = self.owns_server
        super().close()
        if not owned_server and self._server_is_ready():
            self._shutdown_adopted_server()
        self.warmed_up = False

    def _shutdown_adopted_server(self) -> None:
        """Ask the exact local server used by this GUI session to stop."""
        try:
            response = requests.post(
                f"{self.server_url}/shutdown",
                timeout=CANCEL_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"ปิด Whisper Server ที่รับช่วงมาไม่สำเร็จ: {error}")
            return
        deadline = time.monotonic() + 3.0
        while self._server_is_ready() and time.monotonic() < deadline:
            time.sleep(0.05)
