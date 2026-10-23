import asyncio

from core.chat import ChatAI
from core.schemas import ChatResult, WorkerResult
from core.skill_registry import SkillRegistry
from core.worker import WorkerAI


class Controller:
    def __init__(self):
        self.registry = SkillRegistry()
        self.chat = ChatAI(self.registry.catalog())
        self.worker = WorkerAI(self.registry)
        self.pending_execution_result = None
        self.lock = asyncio.Lock()

    @property
    def awaiting_user_input(self) -> bool:
        return self.worker.awaiting_user_input

    async def start(self) -> None:
        await self.chat.start()

    async def generate_chat(self, user_message: str) -> ChatResult:
        if self.awaiting_user_input:
            raise RuntimeError("Worker is waiting for user input")

        async with self.lock:
            result = await self.chat.generate(
                user_message,
                previous_execution_result=self.pending_execution_result,
            )
            self.pending_execution_result = None
            return result

    async def execute_task(self, chat_result: ChatResult) -> WorkerResult | None:
        chat_result = ChatResult.model_validate(chat_result)

        if chat_result.type != "task":
            return None

        result = await self.worker.execute(chat_result.task)
        self.chat.record_worker_result(result.response)

        if result.status != "needs_input":
            self.pending_execution_result = result.response

        return result

    async def continue_task(self, user_message: str) -> WorkerResult:
        result = await self.worker.continue_with_user_input(user_message)
        self.chat.record_worker_continuation(user_message, result.response)

        if result.status != "needs_input":
            self.pending_execution_result = result.response

        return result

    async def rotate_chat_if_ready(self) -> bool:
        if self.awaiting_user_input:
            return False

        return await self.chat.rotate_if_due()

    async def reset_conversation(self, start: bool = True) -> None:
        async with self.lock:
            await self.worker.close()
            await self.chat.reset(start=start)
            self.pending_execution_result = None

    async def cancel_pending_task(self) -> None:
        await self.worker.abort()
        self.pending_execution_result = None

    async def close(self) -> None:
        try:
            await self.worker.close()
        finally:
            try:
                await self.chat.close()
            finally:
                await self.registry.close()
