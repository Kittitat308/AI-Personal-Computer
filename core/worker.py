from pathlib import Path

from core.config import PROMPTS_DIR
from core.schemas import TaskRequest, WorkerResult
from core.skill_registry import SkillRegistry
from providers.base import AIProvider


class WorkerAI:
    def __init__(self, provider: AIProvider, registry: SkillRegistry):
        self.provider = provider
        self.registry = registry
        self.system_prompt = (PROMPTS_DIR / "worker.md").read_text(encoding="utf-8")
        self.allowed_directory: Path | None = None
        self.temporary_attachment_directory: Path | None = None

    @property
    def awaiting_user_input(self) -> bool:
        return self.provider.worker_awaiting_input

    def set_allowed_directory(self, path: str | None) -> None:
        self.allowed_directory = Path(path).resolve() if path else None

    def set_temporary_attachment_directory(self, path: Path | None) -> None:
        self.temporary_attachment_directory = path.resolve() if path else None

    def _allowed_directories(self) -> list[Path]:
        directories = []
        for directory in (
            self.allowed_directory,
            self.temporary_attachment_directory,
        ):
            if directory is not None and directory not in directories:
                directories.append(directory)
        self.temporary_attachment_directory = None
        return directories

    async def execute(self, task: TaskRequest) -> WorkerResult:
        if self.awaiting_user_input:
            raise RuntimeError("Worker is already waiting for user input")
        task = TaskRequest.model_validate(task)
        definitions = self.registry.resolve(task.skill_ids)
        skill_instructions = "\n\n".join(
            f"## Skill: {definition.skill_id}\n\n{definition.instructions}"
            for definition in definitions
            if definition.instructions
        )
        async with self.registry.task_sessions():
            raw = await self.provider.execute_worker(
                task=task,
                system_prompt=self.system_prompt.strip(),
                skill_instructions=skill_instructions,
                definitions=definitions,
                registry=self.registry,
                allowed_directories=self._allowed_directories(),
            )
        return WorkerResult.model_validate(raw)

    async def continue_with_user_input(self, user_message: str) -> WorkerResult:
        async with self.registry.task_sessions():
            raw = await self.provider.continue_worker(user_message)
        return WorkerResult.model_validate(raw)

    async def abort(self) -> None:
        await self.provider.abort_worker()
