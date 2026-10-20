import asyncio
import re
import tempfile
import time
import unicodedata
from html import escape
from pathlib import Path

import aiohttp
import sounddevice as sd
import soundfile as sf

from speech.tts.config import (
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_RATE,
    AZURE_SPEECH_REGION,
    AZURE_SPEECH_VOICE,
    OUTPUT_FORMAT,
    REQUEST_TIMEOUT_SECONDS,
    validate_tts_settings,
)


class TTSService:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._configuration_error: str | None = None

    async def start(self) -> None:
        try:
            validate_tts_settings()
        except RuntimeError as error:
            self._configuration_error = str(error)
            print(f"\nTTS ERROR:\n{error}\n")
            return

        await self._get_session()

    async def speak(self, text: str) -> bool:
        cleaned_text = self.clean_text(text)

        if not cleaned_text:
            return False

        if self._configuration_error is not None:
            print(f"\nTTS ERROR:\n{self._configuration_error}\n")
            return False

        output_path = self._temporary_output_path()
        started = time.perf_counter()

        try:
            await self._synthesize(cleaned_text, output_path)
            await asyncio.to_thread(self._play_blocking, output_path)
            print(f"AZURE TTS TOTAL: {time.perf_counter() - started:.2f} s")
            return True
        except Exception as error:
            print(f"\nTTS ERROR:\n{error}\n")
            return False
        finally:
            output_path.unlink(missing_ok=True)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

        self._session = None

    async def _synthesize(self, text: str, output_path: Path) -> None:
        session = await self._get_session()
        endpoint = (
            f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/"
            "cognitiveservices/v1"
        )
        ssml = (
            "<speak version='1.0' xml:lang='th-TH'>"
            f"<voice name='{escape(AZURE_SPEECH_VOICE)}'>"
            f"<prosody rate='{escape(AZURE_SPEECH_RATE)}'>"
            f"{escape(text)}"
            "</prosody></voice></speak>"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
            "User-Agent": "AI-Personal-Computer",
        }

        try:
            async with session.post(
                endpoint,
                data=ssml.encode("utf-8"),
                headers=headers,
            ) as response:
                audio = await response.read()

                if response.status != 200:
                    raise RuntimeError(
                        f"Azure Speech ตอบกลับด้วยสถานะ {response.status}"
                    )
        except asyncio.TimeoutError as error:
            raise TimeoutError(
                f"Azure TTS ใช้เวลาเกิน {REQUEST_TIMEOUT_SECONDS:.0f} วินาที"
            ) from error
        except aiohttp.ClientError as error:
            raise RuntimeError(
                f"เชื่อมต่อ Azure TTS ไม่สำเร็จ: {type(error).__name__}"
            ) from error

        if not audio:
            raise RuntimeError("Azure TTS ไม่ส่งข้อมูลเสียงกลับมา")

        output_path.write_bytes(audio)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
            self._session = aiohttp.ClientSession(timeout=timeout)

        return self._session

    @staticmethod
    def clean_text(text: str) -> str:
        text = str(text).strip()
        text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"^\s*[-+•▪◦]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"[`*_~#>]", "", text)
        text = "".join(
            character
            for character in text
            if unicodedata.category(character) not in {"So", "Sk", "Cs"}
            and character not in {"\ufe0f", "\u200d"}
        )
        return " ".join(text.split())

    @staticmethod
    def _temporary_output_path() -> Path:
        temporary = tempfile.NamedTemporaryFile(
            prefix="ai_pc_tts_",
            suffix=".wav",
            delete=False,
        )
        temporary.close()
        return Path(temporary.name)

    @staticmethod
    def _play_blocking(output_path: Path) -> None:
        audio, sample_rate = sf.read(
            output_path,
            dtype="float32",
            always_2d=True,
        )
        sd.play(audio, sample_rate)
        sd.wait()
