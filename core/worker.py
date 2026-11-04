import shutil
import tempfile
from pathlib import Path

from core.config import PROMPTS_DIR
from core.schemas import TaskRequest, WorkerResult
from core.skill_registry import SkillRegistry
from providers.base import AIProvider, Workspace


class WorkerAI:
    def __init__(self, provider: AIProvider, registry: SkillRegistry):
        self.provider = provider
        self.registry = registry
        self.system_prompt = (PROMPTS_DIR / "worker.md").read_text(encoding="utf-8")
        self.allowed_directory: Path | None = None
        self.temporary_attachment_directory: Path | None = None
        # Temporary folder of the current task when the user selected no folder.
        self.output_directory: Path | None = None

    @property
    def awaiting_user_input(self) -> bool:
        return self.provider.worker_awaiting_input

    @property
    def pending_permission(self) -> dict | None:
        return self.provider.worker_pending_permission

    @property
    def permission_question(self) -> str:
        return self.provider.worker_permission_question

    def set_allowed_directory(self, path: str | None) -> None:
        self.allowed_directory = Path(path).resolve() if path else None

    def set_temporary_attachment_directory(self, path: Path | None) -> None:
        self.temporary_attachment_directory = path.resolve() if path else None

    def _workspace(self) -> Workspace:
        extra = self.temporary_attachment_directory
        self.temporary_attachment_directory = None
        extra_directories = (extra,) if extra is not None else ()
        if self.allowed_directory is not None:
            return Workspace(self.allowed_directory, True, extra_directories)
        self.output_directory = Path(tempfile.mkdtemp(prefix="ai_pc_task_")).resolve()
        return Workspace(self.output_directory, False, extra_directories)

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
        self.discard_outputs()
        async with self.registry.task_sessions():
            raw = await self.provider.execute_worker(
                task=task,
                system_prompt=self.system_prompt.strip(),
                skill_instructions=skill_instructions,
                definitions=definitions,
                registry=self.registry,
                workspace=self._workspace(),
            )
        return WorkerResult.model_validate(raw)

    async def continue_with_user_input(
        self, user_message: str, progress_callback=None
    ) -> WorkerResult:
        async with self.registry.task_sessions():
            raw = await self.provider.continue_worker(user_message)
        return WorkerResult.model_validate(raw)

    async def answer_permission(self, allow: bool, progress_callback=None) -> WorkerResult:
        async with self.registry.task_sessions():
            raw = await self.provider.answer_worker_permission(allow)
        return WorkerResult.model_validate(raw)

    def collect_outputs(self, destination: Path) -> list[Path]:
        """Move the finished task's files into ``destination`` and drop its folder."""
        directory = self.output_directory
        if directory is None or self.awaiting_user_input:
            return []
        collected: list[Path] = []
        destination.mkdir(parents=True, exist_ok=True)
        for source in sorted(directory.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            target = destination / source.name
            counter = 2
            while target.exists():
                target = destination / f"{source.stem}_{counter}{source.suffix}"
                counter += 1
            shutil.move(str(source), str(target))
            collected.append(target)
        self.discard_outputs()
        return collected

    def discard_outputs(self) -> None:
        directory, self.output_directory = self.output_directory, None
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)

    async def abort(self) -> None:
        try:
            await self.provider.abort_worker()
        finally:
            self.discard_outputs()
