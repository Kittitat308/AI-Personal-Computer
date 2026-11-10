import asyncio
import re
import time
import unicodedata

import numpy as np
import sounddevice as sd

from speech.tts.config import (
    MAX_CHUNK_CHARACTERS,
    MIN_CHUNK_CHARACTERS,
    SAMPLE_RATE,
)


class TTSService:
    def __init__(self) -> None:
        self._engine = None

    async def start(self) -> None:
        if self._engine is not None:
            return

        started = time.perf_counter()
        print("กำลังโหลดโมเดลเสียงพูด Wayu Paxa ด้วย CPU...")
        self._engine = await asyncio.to_thread(self._load_engine)
        print(f"โหลดโมเดลเสียงพูดสำเร็จ: {time.perf_counter() - started:.2f} วินาที")

    @staticmethod
    def _load_engine():
        # Importing the speech libraries takes several seconds, so it happens
        # here, off the event loop, and only when speech is turned on.
        from speech.tts.wayu import WayuTTS

        return WayuTTS()

    async def speak(self, text: str) -> bool:
        cleaned_text = self.clean_text(text)

        if not cleaned_text:
            return False

        if self._engine is None:
            print("\nTTS ERROR:\nระบบเสียงพูดยังไม่ได้เริ่มทำงาน\n")
            return False

        chunks = self.split_text(cleaned_text)
        started = time.perf_counter()
        upcoming = asyncio.create_task(asyncio.to_thread(self._engine.synthesize, chunks[0]))

        try:
            for index in range(len(chunks)):
                audio = await upcoming
                upcoming = None
                if index + 1 < len(chunks):
                    upcoming = asyncio.create_task(
                        asyncio.to_thread(self._engine.synthesize, chunks[index + 1])
                    )
                if audio.size:
                    await asyncio.to_thread(self._play_blocking, audio)
            print(f"TTS TOTAL: {time.perf_counter() - started:.2f} s")
            return True
        except Exception as error:
            print(f"\nTTS ERROR:\n{error}\n")
            return False
        finally:
            if upcoming is not None:
                upcoming.cancel()

    async def close(self) -> None:
        self._engine = None

    @staticmethod
    def split_text(text: str) -> list[str]:
        """Pieces ending at sentence breaks or spaces, none longer than the limit."""
        pieces = [
            piece.strip()
            for piece in re.split(r"(?<=[.!?;:])\s+|\s{2,}", text)
            if piece.strip()
        ]
        chunks: list[str] = []
        for piece in pieces:
            while len(piece) > MAX_CHUNK_CHARACTERS:
                cut = piece.rfind(" ", MIN_CHUNK_CHARACTERS, MAX_CHUNK_CHARACTERS)
                if cut == -1:
                    cut = MAX_CHUNK_CHARACTERS
                chunks.append(piece[:cut].strip())
                piece = piece[cut:].strip()
            if not piece:
                continue
            if chunks and len(chunks[-1]) < MIN_CHUNK_CHARACTERS:
                chunks[-1] = f"{chunks[-1]} {piece}"
            else:
                chunks.append(piece)
        return chunks or [text]

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
            and character not in {"️", "‍"}
        )
        return " ".join(text.split())

    @staticmethod
    def _play_blocking(audio: np.ndarray) -> None:
        sd.play(audio.reshape(-1, 1), SAMPLE_RATE)
        sd.wait()
