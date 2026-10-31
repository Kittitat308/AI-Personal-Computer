from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable


ToolCallback = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]]


class AIProvider(ABC):
    name: str

    def __init__(self, model: str, effort: str = "medium", api_key: str = "") -> None:
        self.model = model
        self.effort = effort
        self.api_key = api_key

    @abstractmethod
    async def generate_chat(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute_worker(
        self,
        *,
        task: Any,
        system_prompt: str,
        skill_instructions: str,
        definitions: list[Any],
        tools: list[Any],
        call_tool: ToolCallback,
        registry: Any,
        allowed_directories: list[Path],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def worker_awaiting_input(self) -> bool:
        return False

    async def continue_worker(self, user_message: str) -> dict[str, Any]:
        raise RuntimeError("Provider นี้ไม่มี Worker ที่กำลังรอข้อมูล")

    async def abort_worker(self) -> None:
        return None

    async def reset_chat(self) -> None:
        return None

    async def close(self) -> None:
        await self.abort_worker()
        await self.reset_chat()
