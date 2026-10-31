from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.attachments import MAX_EXTRACTED_CHARACTERS, extract_file_text
from providers.catalog import DEFAULT_EFFORT


class AIProvider(ABC):
    name: str
    # Providers that hold a fixed resource (such as a server port) must close
    # the old instance before a new one of the same provider is created.
    single_instance = False

    def __init__(self, model: str, effort: str = DEFAULT_EFFORT, api_key: str = "") -> None:
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
        registry: Any,
        allowed_directories: list[Path],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def user_content(self, prompt: str, attachments: list[Path]) -> Any:
        """Text-only message: readable files are inlined, others are listed."""
        if not attachments:
            return prompt
        sections = [prompt]
        for path in attachments:
            resolved = path.resolve()
            try:
                text = extract_file_text(resolved)[:MAX_EXTRACTED_CHARACTERS]
            except Exception:
                sections.append(f"ไฟล์ที่ผู้ใช้แนบ: {resolved.name}\nตำแหน่งไฟล์: {resolved}")
                continue
            sections.append(
                f"ไฟล์ที่ผู้ใช้แนบ: {resolved.name}\n"
                f"ตำแหน่งไฟล์สำหรับ Worker: {resolved}\n"
                f"เนื้อหาที่สกัดได้จากไฟล์:\n{text}"
            )
        return "\n\n".join(sections)

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
