import asyncio

from core.chat import ChatAI
from core.admin import AdminAI
from core.confirmation import ConfirmationAI
from core.schemas import AdminResult, ChatResult, WorkerResult
from core.skill_registry import SkillRegistry
from core.worker import WorkerAI


class Controller:
    def __init__(self):
        self.registry = SkillRegistry()
        self.chat = ChatAI(self.registry.catalog())
        self.worker = WorkerAI(self.registry)
        self.admin = AdminAI()
        self.confirmation = ConfirmationAI()
        self.admin_permission_mode = "ask"
        self.pending_execution_result = None
        self.lock = asyncio.Lock()

    def set_admin_permission_mode(self, mode: str) -> None:
        if mode not in {"ask", "auto"}:
            raise ValueError("Admin permission mode must be 'ask' or 'auto'")
        self.admin_permission_mode = mode

    @property
    def awaiting_user_input(self) -> bool:
        return self.worker.awaiting_user_input or self.admin.awaiting_user_input

    async def start(self) -> None:
        await self.chat.start()

    async def generate_chat(
        self,
        user_message: str,
        attachments=None,
    ) -> ChatResult:
        if self.awaiting_user_input:
            raise RuntimeError("Worker is waiting for user input")

        async with self.lock:
            result = await self.chat.generate(
                user_message,
                previous_execution_result=self.pending_execution_result,
                attachments=attachments,
            )
            self.pending_execution_result = None
            return result

    async def execute_task(
        self,
        chat_result: ChatResult,
        progress_callback=None,
    ) -> WorkerResult | AdminResult | None:
        chat_result = ChatResult.model_validate(chat_result)

        if chat_result.type != "task":
            return None

        if "admin" in chat_result.task.skill_ids:
            result = await self.admin.execute(
                chat_result.task,
                progress_callback=progress_callback,
            )
            result = await self._resolve_admin_permissions(
                result,
                progress_callback,
            )
        else:
            result = await self.worker.execute(chat_result.task)
        self.chat.record_worker_result(result.response)

        if result.status != "needs_input":
            self.pending_execution_result = result.response

        return result

    async def continue_task(
        self,
        user_message: str,
        progress_callback=None,
    ) -> WorkerResult | AdminResult:
        if self.admin.awaiting_user_input:
            if self.admin.pending_permission is not None:
                if self.admin_permission_mode == "auto":
                    result = await self.admin.continue_with_user_input(
                        "อนุญาต",
                        progress_callback=progress_callback,
                    )
                else:
                    permission_question = self.admin._permission_question(
                        self.admin.pending_permission
                    )
                    try:
                        decision = await self.confirmation.classify(
                            permission_question,
                            user_message,
                        )
                    except Exception as error:
                        print(f"CONFIRMATION ERROR: {error}")
                        decision = "unclear"
                    if decision == "unclear":
                        result = AdminResult(
                            status="needs_input",
                            response="กรุณาตอบว่าอนุญาตหรือไม่อนุญาตครับ",
                        )
                    else:
                        result = await self.admin.continue_with_user_input(
                            "อนุญาต" if decision == "allow" else "ไม่อนุญาต",
                            progress_callback=progress_callback,
                        )
            else:
                result = await self.admin.continue_with_user_input(
                    user_message,
                    progress_callback=progress_callback,
                )
            result = await self._resolve_admin_permissions(
                result,
                progress_callback,
            )
        else:
            result = await self.worker.continue_with_user_input(user_message)
        self.chat.record_worker_continuation(user_message, result.response)

        if result.status != "needs_input":
            self.pending_execution_result = result.response

        return result

    async def _resolve_admin_permissions(
        self,
        result: AdminResult,
        progress_callback=None,
    ) -> AdminResult:
        while (
            self.admin_permission_mode == "auto"
            and result.status == "needs_input"
            and self.admin.pending_permission is not None
        ):
            result = await self.admin.continue_with_user_input(
                "อนุญาต",
                progress_callback=progress_callback,
            )
        return result

    async def rotate_chat_if_ready(self) -> bool:
        if self.awaiting_user_input:
            return False

        return await self.chat.rotate_if_due()

    async def reset_conversation(self, start: bool = True) -> None:
        async with self.lock:
            await asyncio.gather(self.worker.close(), self.admin.close())
            await self.chat.reset(start=start)
            self.admin_permission_mode = "ask"
            self.pending_execution_result = None

    async def cancel_pending_task(self) -> None:
        await asyncio.gather(self.worker.abort(), self.admin.abort())
        self.pending_execution_result = None

    async def close(self) -> None:
        try:
            await asyncio.gather(self.worker.close(), self.admin.close())
        finally:
            try:
                await self.chat.close()
            finally:
                await self.registry.close()
