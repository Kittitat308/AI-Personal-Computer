import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClaudeResponse:
    text: str
    structured_output: Any | None


class ClaudeSession:
    def __init__(self, arguments: list[str], cwd: Path):
        self.arguments = arguments
        self.cwd = cwd
        self.process = None
        self.lock = asyncio.Lock()
        self.shutdown_lock = asyncio.Lock()
        self.stderr_task = None
        self.stderr_lines: list[str] = []

    async def start(self) -> None:
        if self.process is not None:
            return

        executable = shutil.which("claude")

        if executable is None:
            raise RuntimeError("ไม่พบ Claude CLI ใน PATH")

        self.process = await asyncio.create_subprocess_exec(
            executable,
            *self.arguments,
            cwd=str(self.cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stderr(self) -> None:
        while self.process is not None:
            line = await self.process.stderr.readline()

            if not line:
                return

            message = line.decode("utf-8", errors="replace").strip()

            if message:
                self.stderr_lines.append(message)
                self.stderr_lines = self.stderr_lines[-20:]

    async def generate(self, message: str) -> ClaudeResponse:
        message = str(message).strip()

        if not message:
            raise ValueError("ข้อความต้องไม่ว่าง")

        await self.start()

        async with self.lock:
            if self.process.returncode is not None:
                raise RuntimeError(self._process_error())

            request = {
                "type": "user",
                "message": {"role": "user", "content": message},
                "parent_tool_use_id": None,
                "session_id": "",
            }
            payload = json.dumps(request, ensure_ascii=False) + "\n"
            self.process.stdin.write(payload.encode("utf-8"))
            await self.process.stdin.drain()

            assistant_text = ""

            while True:
                line = await self.process.stdout.readline()

                if not line:
                    raise RuntimeError(self._process_error())

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "assistant":
                    content = event.get("message", {}).get("content", [])
                    current_text = "".join(
                        item.get("text", "")
                        for item in content
                        if item.get("type") == "text"
                    ).strip()
                    assistant_text = current_text or assistant_text

                if event.get("type") != "result":
                    continue

                if event.get("is_error"):
                    raise RuntimeError(event.get("result") or self._process_error())

                result_text = event.get("result")

                if not isinstance(result_text, str):
                    result_text = ""

                return ClaudeResponse(
                    text=result_text.strip() or assistant_text,
                    structured_output=event.get("structured_output"),
                )

    def _process_error(self) -> str:
        if self.stderr_lines:
            return self.stderr_lines[-1]

        if self.process is not None and self.process.returncode is not None:
            return f"Claude CLI ปิดการทำงานด้วย exit code {self.process.returncode}"

        return "Claude CLI connection closed"

    async def close(self) -> None:
        process = self.process

        if process is None:
            return

        if process.stdin is not None:
            process.stdin.close()

            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()

        if self.stderr_task is not None:
            await self.stderr_task

        self.process = None
        self.stderr_task = None

    async def abort(self) -> None:
        """Immediately terminate an in-flight CLI request and discard the session."""
        async with self.shutdown_lock:
            process = self.process
            stderr_task = self.stderr_task
            if process is None:
                return
            if process.returncode is None:
                process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass
            if stderr_task is not None and not stderr_task.done():
                stderr_task.cancel()
                try:
                    await asyncio.wait_for(stderr_task, timeout=1)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            self.process = None
            self.stderr_task = None
