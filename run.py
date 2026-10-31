import asyncio
import time

from core.controller import Controller
from core.config import (
    RUN_AI_PROVIDER,
    RUN_CLAUDE_MODEL,
    RUN_GEMINI_API_KEY,
    RUN_GEMINI_MODEL,
    RUN_MODEL_EFFORT,
)
from providers.qwen import DEFAULT_QWEN_MODEL
from app.stt_adapter import GUISTTService
from speech.wakeword import WakeWordService
from speech.wakeword.config import WAKEWORD_NAME
from speech.tts import AudioQueue


async def main() -> None:
    models = {
        "qwen": DEFAULT_QWEN_MODEL,
        "gemini": RUN_GEMINI_MODEL,
        "claude": RUN_CLAUDE_MODEL,
    }
    controller = Controller(
        provider_name=RUN_AI_PROVIDER,
        model=models.get(RUN_AI_PROVIDER, RUN_CLAUDE_MODEL),
        effort=RUN_MODEL_EFFORT,
        api_key=RUN_GEMINI_API_KEY if RUN_AI_PROVIDER == "gemini" else "",
    )
    stt = GUISTTService()
    audio_queue = AudioQueue()
    wakeword = WakeWordService()

    def show_admin_progress(message: str) -> None:
        print(f"\nADMIN PROGRESS:\n{message}")
        audio_queue.enqueue(message)

    try:
        await asyncio.gather(
            controller.start(),
            asyncio.to_thread(stt.start),
            asyncio.to_thread(wakeword.start),
            audio_queue.start(),
        )
        print("\nAI Personal Computer พร้อมใช้งาน")
        print(
            f"พูดว่า '{WAKEWORD_NAME}' เพื่อเริ่มพูดคำสั่ง "
            "และพูดว่า 'ปิดระบบ' เพื่อออก\n"
        )

        while True:
            try:
                audio = await asyncio.to_thread(wakeword.listen_for_command)
                if not audio.size:
                    print(
                        f"ไม่ได้ยินคำสั่ง กรุณาพูด {WAKEWORD_NAME} "
                        "แล้วลองใหม่ครับ\n"
                    )
                    continue
                stt.prepare_transcription()
                message = (await asyncio.to_thread(stt.transcribe_audio, audio)).strip()
            except Exception as error:
                print(f"\nSTT ERROR:\n{error}\n")
                continue

            if not message:
                print("ไม่ได้ยินข้อความ กรุณาลองใหม่ครับ\n")
                continue

            print(f"\nคุณ: {message}")

            if stt.is_shutdown_command(message):
                break

            started = time.perf_counter()

            try:
                if controller.awaiting_user_input:
                    worker_result = await controller.continue_task(
                        message,
                        progress_callback=show_admin_progress,
                    )
                    print(f"\nWORKER:\n{worker_result.response}")
                    audio_queue.enqueue(worker_result.response)
                else:
                    chat_result = await controller.generate_chat(message)
                    print(f"\nCHAT:\n{chat_result.model_dump()}")
                    print(f"\nAI:\n{chat_result.response}")
                    audio_queue.enqueue(chat_result.response)

                    worker_result = await controller.execute_task(
                        chat_result,
                        progress_callback=show_admin_progress,
                    )

                    if worker_result is not None:
                        print(f"\nWORKER:\n{worker_result.response}")
                        audio_queue.enqueue(worker_result.response)

                rotated = await controller.rotate_chat_if_ready()

                if rotated:
                    print("\nCHAT SESSION: เริ่ม Session ใหม่แล้ว")
            except Exception as error:
                print(f"\nSYSTEM ERROR:\n{error}")
            finally:
                await audio_queue.wait_until_idle()

            print(f"TOTAL: {time.perf_counter() - started:.2f} s\n")
    finally:
        wakeword.close()
        await asyncio.to_thread(stt.close)
        try:
            await audio_queue.close()
        finally:
            await controller.close()
        print("ปิดระบบแล้ว")


if __name__ == "__main__":
    asyncio.run(main())
