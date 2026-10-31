import asyncio

from core.admin import AdminAI
from core.chat import ChatAI
from core.confirmation import ConfirmationAI
from core.schemas import AdminResult, ChatResult, WorkerResult
from core.skill_registry import SkillRegistry
from core.worker import WorkerAI
from providers import create_provider
from providers.catalog import DEFAULT_EFFORT, DEFAULT_PROVIDER, provider_info


class Controller:
    def __init__(
        self,
        provider_name: str = DEFAULT_PROVIDER,
        model: str = "",
        effort: str = DEFAULT_EFFORT,
        api_key: str = "",
    ):
        self.registry = SkillRegistry(provider_name)
        self.admin = AdminAI()
        self.confirmation = ConfirmationAI()
        self.admin_permission_mode = "ask"
        self.lock = asyncio.Lock()
        self._install(create_provider(provider_name, model, effort, api_key))

    def _install(self, provider) -> None:
        self.provider = provider
        self.registry.set_provider(provider.name)
        self.chat = ChatAI(provider, self.registry.catalog())
        self.worker = WorkerAI(provider, self.registry)
        self.pending_execution_result = None

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
        effort: str = DEFAULT_EFFORT,
        api_key: str = "",
    ) -> None:
        info = provider_info(name)
        model = model.strip() or info.default_model
        effort = effort.strip().casefold() or DEFAULT_EFFORT
        api_key = api_key.strip() if info.uses_api_key else ""
        if (
            self.provider.name == info.name
            and self.provider.model == model
            and self.provider.effort == effort
            and self.provider.api_key == api_key
        ):
            return
        async with self.lock:
            old_provider = self.provider
            # A single-instance provider holds a fixed resource, so the old one
            # must stop before the new one can start.
            close_first = old_provider.single_instance and old_provider.name == info.name
            if close_first:
                await asyncio.gather(self.worker.abort(), self.chat.close())
                await old_provider.close()
            try:
                new_provider = create_provider(info.name, model, effort, api_key)
            except Exception:
                if close_first:
                    self._install(
                        create_provider(
                            old_provider.name,
                            old_provider.model,
                            old_provider.effort,
                            old_provider.api_key,
                        )
                    )
                raise
            if not close_first:
                try:
                    await asyncio.gather(self.worker.abort(), self.chat.close())
                except Exception:
                    await new_provider.close()
                    raise
            self._install(new_provider)
            if not close_first:
                await old_provider.close()

    def set_admin_permission_mode(self, mode: str) -> None:
        if mode not in {"ask", "auto"}:
            raise ValueError("Admin permission mode must be 'ask' or 'auto'")
        self.admin_permission_mode = mode

    @property
    def awaiting_user_input(self) -> bool:
        return self.worker.awaiting_user_input or self.admin.awaiting_user_input

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

    async def reset_conversation(self) -> None:
        async with self.lock:
            await asyncio.gather(self.worker.abort(), self.admin.abort())
            await self.chat.reset()
            self.admin_permission_mode = "ask"
            self.pending_execution_result = None

    async def cancel_pending_task(self) -> None:
        await asyncio.gather(self.worker.abort(), self.admin.abort())
        self.pending_execution_result = None

    async def close(self) -> None:
        try:
            await asyncio.gather(self.worker.abort(), self.admin.abort())
        finally:
            try:
                await self.provider.close()
            finally:
                await self.registry.close()
