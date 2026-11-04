import os
import platform
import shutil
from pathlib import Path
from typing import Callable

from core.claude_cli import (
    ClaudeResponse,
    ClaudeSession,
    InteractiveSession,
    stream_json_arguments,
)
from core.config import ADMIN_EFFORT, ADMIN_MODEL, PROMPTS_DIR
from core.schemas import AdminResult, TaskRequest


ProgressCallback = Callable[[str], object]


class AdminAI:
    """One temporary, permission-aware Claude CLI session per admin task."""

    def __init__(
        self,
        model: str = ADMIN_MODEL,
        effort: str = ADMIN_EFFORT,
    ):
        self.model = model
        self.effort = effort
        self.system_prompt = (PROMPTS_DIR / "admin.md").read_text(encoding="utf-8")
        self.session: InteractiveSession | None = None
        self.progress_callback: ProgressCallback | None = None
        self.last_progress = ""

    @property
    def awaiting_user_input(self) -> bool:
        return self.session is not None

    @property
    def pending_permission(self) -> dict | None:
        return None if self.session is None else self.session.pending_permission

    @property
    def permission_question(self) -> str:
        if self.session is None:
            raise RuntimeError("Admin is not waiting for a permission decision")
        return self.session.question

    def _create_session(self) -> ClaudeSession:
        arguments = stream_json_arguments(
            model=self.model,
            effort=self.effort,
            system_prompt=self.system_prompt.strip(),
            schema=AdminResult.model_json_schema(),
        )
        arguments += [
            "--tools",
            "default",
            "--permission-mode",
            "manual",
            "--permission-prompts",
            "host",
            "--permission-prompt-tool",
            "stdio",
            "--setting-sources",
            "user,project,local",
        ]
        return ClaudeSession(
            arguments,
            Path.home(),
            isolated_process_group=True,
        )

    def _runtime_context(self) -> str:
        system = platform.system()
        architecture = platform.machine() or "unknown"
        release = platform.release() or "unknown"
        device = "PC"

        if system == "Linux":
            model_path = Path("/proc/device-tree/model")
            if model_path.is_file():
                try:
                    device = model_path.read_text(encoding="utf-8").strip("\x00\n ")
                except OSError:
                    device = "Linux computer"
            else:
                device = "Linux computer"

        shell = os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"
        package_managers = [
            name
            for name in ("apt", "dnf", "pacman", "winget", "brew", "pip", "pip3")
            if shutil.which(name)
        ]
        venv = os.environ.get("VIRTUAL_ENV") or "not active"

        return "\n".join(
            [
                f"- Operating system: {system} {release}",
                f"- Architecture: {architecture}",
                f"- Device: {device}",
                f"- Current user: {os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'}",
                f"- Home directory: {Path.home()}",
                f"- Shell: {shell}",
                f"- Python: {platform.python_version()}",
                f"- Active virtual environment: {venv}",
                "- Available package managers: "
                + (", ".join(package_managers) if package_managers else "none detected"),
                "- This is startup context. Recheck changing state only when the task depends on it.",
            ]
        )

    def _task_prompt(self, task: TaskRequest) -> str:
        return (
            "Delegated admin task:\n"
            + task.instruction.strip()
            + "\n\nRuntime context:\n"
            + self._runtime_context()
        )

    async def execute(
        self,
        task: TaskRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> AdminResult:
        if self.session is not None:
            raise RuntimeError("Admin is already handling a task")

        task = TaskRequest.model_validate(task)
        if task.skill_ids != ["admin"]:
            raise ValueError("Admin tasks must use only the admin capability")

        self.session = InteractiveSession(
            self._create_session(), on_assistant_text=self._on_assistant_text
        )
        self.progress_callback = progress_callback
        self.last_progress = ""
        self.session.start_turn(self._task_prompt(task))
        return await self._wait()

    async def continue_with_user_input(
        self,
        user_message: str,
        progress_callback: ProgressCallback | None = None,
    ) -> AdminResult:
        if self.session is None or self.session.pending_permission is not None:
            raise RuntimeError("Admin is not waiting for an answer")
        if progress_callback is not None:
            self.progress_callback = progress_callback
        self.session.start_turn(
            "ผู้ใช้ตอบคำถามของคุณว่า:\n"
            + user_message.strip()
            + "\n\nให้ทำงาน Admin เดิมต่อจนเสร็จ"
        )
        return await self._wait()

    async def answer_permission(
        self,
        allow: bool,
        progress_callback: ProgressCallback | None = None,
    ) -> AdminResult:
        if self.session is None:
            raise RuntimeError("Admin is not waiting for a permission decision")
        if progress_callback is not None:
            self.progress_callback = progress_callback
        await self.session.answer_permission(allow)
        return await self._wait()

    async def _wait(self) -> AdminResult:
        try:
            response = await self.session.wait()
            if response is None:
                return AdminResult(status="needs_input", response=self.session.question)
            result = self._parse_result(response)
        except BaseException:
            await self.abort()
            raise
        if result.status != "needs_input":
            await self._finish_session()
        return result

    def _on_assistant_text(self, text: str) -> None:
        marker = "[progress] "
        messages = [
            line[len(marker) :].strip()
            for line in text.splitlines()
            if line.strip().startswith(marker)
        ]
        if not messages:
            return
        message = messages[-1]
        if not message or message == self.last_progress:
            return
        self.last_progress = message
        if self.progress_callback is not None:
            self.progress_callback(message)

    @staticmethod
    def _parse_result(response: ClaudeResponse) -> AdminResult:
        if response.structured_output is not None:
            return AdminResult.model_validate(response.structured_output)
        try:
            return AdminResult.model_validate_json(response.text)
        except Exception as error:
            raise RuntimeError(f"Admin returned invalid structured output: {error}") from error

    async def _finish_session(self) -> None:
        session, self.session = self.session, None
        self.progress_callback = None
        if session is not None:
            await session.close()

    async def abort(self) -> None:
        session, self.session = self.session, None
        self.progress_callback = None
        if session is not None:
            await session.abort()
