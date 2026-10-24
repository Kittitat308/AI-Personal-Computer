import asyncio
import contextlib
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Callable

from core.claude_cli import ClaudeResponse, ClaudeSession
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
        self.active_session: ClaudeSession | None = None
        self.running_session: ClaudeSession | None = None
        self.turn_task: asyncio.Task | None = None
        self.permission_queue: asyncio.Queue = asyncio.Queue()
        self.pending_permission: dict | None = None
        self.progress_callback: ProgressCallback | None = None
        self.last_progress = ""

    @property
    def awaiting_user_input(self) -> bool:
        return self.active_session is not None

    def _create_session(self) -> ClaudeSession:
        schema = json.dumps(AdminResult.model_json_schema(), ensure_ascii=False)
        arguments = [
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--effort",
            self.effort,
            "--system-prompt",
            self.system_prompt.strip(),
            "--json-schema",
            schema,
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
            "--no-session-persistence",
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
        if self.active_session is not None or self.turn_task is not None:
            raise RuntimeError("Admin is already handling a task")

        task = TaskRequest.model_validate(task)
        if task.skill_ids != ["admin"]:
            raise ValueError("Admin tasks must use only the admin capability")

        session = self._create_session()
        self.permission_queue = asyncio.Queue()
        self.active_session = session
        self.running_session = session
        self.progress_callback = progress_callback
        self.last_progress = ""
        self._start_turn(self._task_prompt(task))
        return await self._await_turn_or_permission()

    async def continue_with_user_input(
        self,
        user_message: str,
        progress_callback: ProgressCallback | None = None,
    ) -> AdminResult:
        if self.active_session is None:
            raise RuntimeError("Admin is not waiting for user input")

        if progress_callback is not None:
            self.progress_callback = progress_callback

        if self.pending_permission is not None:
            decision = self._confirmation_decision(user_message)
            if decision is None:
                return AdminResult(
                    status="needs_input",
                    response="กรุณาตอบว่ายืนยันหรือไม่อนุญาตครับ",
                )

            permission = self.pending_permission
            self.pending_permission = None
            await self.active_session.respond_to_permission(
                permission["request_id"],
                permission["request"].get("input", {}),
                decision,
            )
            return await self._await_turn_or_permission()

        self.running_session = self.active_session
        self._start_turn(
            "ผู้ใช้ตอบคำถามของคุณว่า:\n"
            + user_message.strip()
            + "\n\nให้ทำงาน Admin เดิมต่อจนเสร็จ"
        )
        return await self._await_turn_or_permission()

    def _start_turn(self, prompt: str) -> None:
        if self.active_session is None:
            raise RuntimeError("Admin session is not active")
        self.turn_task = asyncio.create_task(
            self.active_session.generate(
                prompt,
                on_assistant_text=self._on_assistant_text,
                on_permission_request=self._on_permission_request,
            )
        )

    async def _await_turn_or_permission(self) -> AdminResult:
        if self.turn_task is None:
            raise RuntimeError("Admin turn is not running")

        permission_waiter = asyncio.create_task(self.permission_queue.get())
        try:
            done, _ = await asyncio.wait(
                {self.turn_task, permission_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if self.turn_task in done:
                permission_waiter.cancel()
                response = await self.turn_task
                self.turn_task = None
                self.running_session = None
                result = self._parse_result(response)

                if result.status != "needs_input":
                    await self._finish_session()

                return result

            self.pending_permission = permission_waiter.result()
            return AdminResult(
                status="needs_input",
                response=self._permission_question(self.pending_permission),
            )
        except asyncio.CancelledError:
            await self.abort()
            raise
        except Exception:
            await self.abort()
            raise
        finally:
            if not permission_waiter.done():
                permission_waiter.cancel()

    def _on_permission_request(self, event: dict) -> None:
        self.permission_queue.put_nowait(event)

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

    def _permission_question(self, event: dict) -> str:
        request = event.get("request", {})
        description = str(request.get("description") or "").strip()
        if description:
            description = description.rstrip(".。 ")
            return f"{description} ยืนยันให้ดำเนินการไหมครับ"

        tool_name = request.get("tool_name", "คำสั่งระบบ")
        return f"Admin ต้องใช้ {tool_name} เพื่อทำงานต่อ ยืนยันไหมครับ"

    @staticmethod
    def _confirmation_decision(message: str) -> bool | None:
        normalized = " ".join(message.casefold().strip().split())
        for suffix in ("ครับ", "ค่ะ", "คะ", "คับ"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)].strip()
                break
        deny_phrases = (
            "ไม่",
            "ไม่อนุญาต",
            "ไม่ยืนยัน",
            "ยกเลิก",
            "หยุด",
            "no",
            "deny",
            "cancel",
        )
        allow_phrases = (
            "ยืนยัน",
            "อนุญาต",
            "ตกลง",
            "ได้",
            "ทำเลย",
            "ใช่",
            "โอเค",
            "ok",
            "yes",
            "allow",
        )

        if normalized in deny_phrases or normalized.startswith("ไม่"):
            return False
        if normalized in allow_phrases:
            return True
        return None

    @staticmethod
    def _parse_result(response: ClaudeResponse) -> AdminResult:
        if response.structured_output is not None:
            return AdminResult.model_validate(response.structured_output)
        try:
            return AdminResult.model_validate_json(response.text)
        except Exception as error:
            raise RuntimeError(f"Admin returned invalid structured output: {error}") from error

    async def _finish_session(self) -> None:
        session = self.active_session
        self.active_session = None
        self.running_session = None
        self.turn_task = None
        self.pending_permission = None
        self.progress_callback = None
        if session is not None:
            await session.close()

    async def close(self) -> None:
        await self.abort()

    async def abort(self) -> None:
        turn_task = self.turn_task
        session = self.active_session or self.running_session
        self.active_session = None
        self.running_session = None
        self.turn_task = None
        self.pending_permission = None
        self.progress_callback = None

        if turn_task is not None and not turn_task.done():
            turn_task.cancel()
        if session is not None:
            await session.abort()
        if turn_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await turn_task
