import asyncio

from core.admin import AdminAI
from core.chat import ChatAI
from core.confirmation import ConfirmationAI
from core.schemas import AdminResult, ChatResult, WorkerResult
from core.skill_registry import SkillRegistry
from core.worker import WorkerAI
from providers import ClaudeProvider, GeminiProvider, QwenProvider
from providers.qwen import DEFAULT_QWEN_MODEL


class Controller:
    def __init__(
        self,
        provider_name: str = "claude",
        model: str | None = None,
        effort: str = "medium",
        api_key: str = "",
    ):
        provider_name = provider_name.strip().casefold()
        self.registry = SkillRegistry(provider_name)
        self.admin = AdminAI()
        self.confirmation = ConfirmationAI()
        self.admin_permission_mode = "ask"
        self.pending_execution_result = None
        self.lock = asyncio.Lock()
        self.provider = self._create_provider(
            provider_name,
            model.strip() if model else self._default_model(provider_name),
            effort,
            api_key,
        )
        self.chat = ChatAI(self.provider, self.registry.catalog())
        self.worker = WorkerAI(self.provider, self.registry)

    @staticmethod
    def _default_model(provider_name: str) -> str:
        return {
            "qwen": DEFAULT_QWEN_MODEL,
            "gemini": "gemini-3.5-flash-lite",
            "claude": "haiku",
        }.get(provider_name, "haiku")

    @staticmethod
    def _create_provider(name: str, model: str, effort: str, api_key: str):
        factories = {
            "qwen": QwenProvider,
            "gemini": GeminiProvider,
            "claude": ClaudeProvider,
        }
        normalized = name.strip().casefold()
        if normalized not in factories:
            raise ValueError("AI provider ต้องเป็น qwen, gemini หรือ claude")
        return factories[normalized](model=model, effort=effort, api_key=api_key)

    @property
    def provider_name(self) -> str:
        return self.provider.name

    @property
    def provider_model(self) -> str:
        return self.provider.model

    @property
    def provider_effort(self) -> str:
        return self.provider.effort

    async def configure_provider(
        self,
        name: str,
        model: str,
        effort: str = "medium",
        api_key: str = "",
    ) -> None:
        normalized = name.strip().casefold()
        model = model.strip() or self._default_model(normalized)
        effort = effort.strip().casefold() or "medium"
        if (
            self.provider.name == normalized
            and self.provider.model == model
            and self.provider.effort == effort
            and (normalized != "gemini" or self.provider.api_key == api_key.strip())
        ):
            return
        async with self.lock:
            old_provider = self.provider
            old_configuration = (
                old_provider.name,
                old_provider.model,
                old_provider.effort,
                old_provider.api_key,
            )
            if old_provider.name == normalized == "qwen":
                await asyncio.gather(self.worker.close(), self.chat.close())
                await old_provider.close()
                try:
                    new_provider = self._create_provider(
                        normalized, model, effort, api_key
                    )
                except Exception:
                    restored = self._create_provider(*old_configuration)
                    self.provider = restored
                    self.chat = ChatAI(restored, self.registry.catalog())
                    self.worker = WorkerAI(restored, self.registry)
                    raise
                self.provider = new_provider
                self.registry.set_provider(normalized)
                self.chat = ChatAI(new_provider, self.registry.catalog())
                self.worker = WorkerAI(new_provider, self.registry)
                self.pending_execution_result = None
                return
            new_provider = self._create_provider(
                normalized, model, effort, api_key
            )
            try:
                await asyncio.gather(self.worker.close(), self.chat.close())
            except Exception:
                await new_provider.close()
                raise
            self.provider = new_provider
            self.registry.set_provider(normalized)
            self.chat = ChatAI(new_provider, self.registry.catalog())
            self.worker = WorkerAI(new_provider, self.registry)
            self.pending_execution_result = None
            await old_provider.close()

    def set_admin_permission_mode(self, mode: str) -> None:
        if mode not in {"ask", "auto"}:
            raise ValueError("Admin permission mode must be 'ask' or 'auto'")
        self.admin_permission_mode = mode

    @property
    def awaiting_user_input(self) -> bool:
        return self.worker.awaiting_user_input or self.admin.awaiting_user_input

    async def start(self) -> None:
        await self.chat.start()

    async def generate_chat(self, user_message: str, attachments=None) -> ChatResult:
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
                chat_result.task, progress_callback=progress_callback
            )
            result = await self._resolve_admin_permissions(result, progress_callback)
        else:
            result = await self.worker.execute(chat_result.task)
        self.chat.record_worker_result(result.response)
        if result.status != "needs_input":
            self.pending_execution_result = result.response
        return result

    async def continue_task(self, user_message: str, progress_callback=None):
        if self.admin.awaiting_user_input:
            if self.admin.pending_permission is not None:
                if self.admin_permission_mode == "auto":
                    result = await self.admin.continue_with_user_input(
                        "อนุญาต", progress_callback=progress_callback
                    )
                else:
                    question = self.admin._permission_question(
                        self.admin.pending_permission
                    )
                    try:
                        decision = await self.confirmation.classify(
                            question, user_message
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
                    user_message, progress_callback=progress_callback
                )
            result = await self._resolve_admin_permissions(result, progress_callback)
        else:
            result = await self.worker.continue_with_user_input(user_message)
        self.chat.record_worker_continuation(user_message, result.response)
        if result.status != "needs_input":
            self.pending_execution_result = result.response
        return result

    async def _resolve_admin_permissions(self, result, progress_callback=None):
        while (
            self.admin_permission_mode == "auto"
            and result.status == "needs_input"
            and self.admin.pending_permission is not None
        ):
            result = await self.admin.continue_with_user_input(
                "อนุญาต", progress_callback=progress_callback
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
                await self.provider.close()
            finally:
                await self.registry.close()
