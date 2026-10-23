import asyncio

import sounddevice as sd

from speech.tts.tts import TTSService


class AudioQueue:
    def __init__(self, tts: TTSService | None = None) -> None:
        self.tts = tts or TTSService()
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._consumer: asyncio.Task | None = None

    async def start(self) -> None:
        if self._consumer is not None:
            return

        await self.tts.start()
        self._consumer = asyncio.create_task(
            self._consume(),
            name="tts-audio-queue",
        )

    def enqueue(self, text: str) -> None:
        if self._consumer is None:
            raise RuntimeError("Audio Queue ยังไม่ได้เริ่มทำงาน")

        if isinstance(text, str) and text.strip():
            self._queue.put_nowait(text.strip())

    async def wait_until_idle(self) -> None:
        await self._queue.join()

    @staticmethod
    def stop_playback() -> None:
        sd.stop()

    async def cancel(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self._queue.task_done()

        await asyncio.to_thread(self.stop_playback)
        if self._consumer is not None:
            self._consumer.cancel()
            try:
                await self._consumer
            except asyncio.CancelledError:
                pass
            self._consumer = asyncio.create_task(
                self._consume(),
                name="tts-audio-queue",
            )

    async def close(self) -> None:
        if self._consumer is not None:
            await self._queue.join()
            self._queue.put_nowait(None)
            await self._consumer
            self._consumer = None

        await self.tts.close()

    async def _consume(self) -> None:
        while True:
            text = await self._queue.get()

            try:
                if text is None:
                    return

                await self.tts.speak(text)
            finally:
                self._queue.task_done()
