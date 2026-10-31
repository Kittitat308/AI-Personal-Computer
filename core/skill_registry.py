import asyncio
import os
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from core.config import PROJECT_ROOT, SKILLS_DIR


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    description: str
    directory: Path | None
    tool_names: tuple[str, ...]
    builtin_tool_names: tuple[str, ...] = ()
    runtime_dependencies: tuple[str, ...] = ()
    worker_dependencies: tuple[str, ...] = ()
    working_directory: Path | None = None

    @property
    def instructions(self) -> str:
        if self.directory is None:
            return ""

        return (self.directory / "SKILL.md").read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class ToolDefinition:
    skill_id: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class SkillRuntime:
    def __init__(self, definition: SkillDefinition):
        self.definition = definition
        self.process = None
        self.port = None
        self.stderr_task = None
        self.stderr_lines: list[str] = []
        self.lock = asyncio.Lock()
        self.environment_overrides: dict[str, str] = {}

    async def start(self) -> None:
        async with self.lock:
            if self.process is not None and self.process.returncode is None:
                return

            self.port = self._find_free_port()
            environment = os.environ.copy()
            environment.update(self.environment_overrides)
            port_variable = f"{self.definition.skill_id.upper()}_MCP_PORT"
            environment[port_variable] = str(self.port)
            server_path = self.definition.directory / "server.py"
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(server_path),
                cwd=str(self.definition.directory),
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            self.stderr_task = asyncio.create_task(self._read_stderr())

            try:
                await self._wait_until_ready()
            except Exception:
                await self.close()
                raise

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    async def _wait_until_ready(self) -> None:
        for _ in range(100):
            if self.process.returncode is not None:
                details = self.stderr_lines[-1] if self.stderr_lines else ""
                raise RuntimeError(
                    f"{self.definition.skill_id} MCP server stopped during startup"
                    + (f": {details}" if details else "")
                )

            try:
                _, writer = await asyncio.open_connection("127.0.0.1", self.port)
            except OSError:
                await asyncio.sleep(0.05)
                continue

            writer.close()
            await writer.wait_closed()
            return

        raise TimeoutError(f"Timed out starting {self.definition.skill_id} MCP server")

    async def _read_stderr(self) -> None:
        while self.process is not None:
            line = await self.process.stderr.readline()

            if not line:
                return

            message = line.decode("utf-8", errors="replace").strip()

            if message:
                self.stderr_lines.append(message)
                self.stderr_lines = self.stderr_lines[-30:]

    @property
    def mcp_config(self) -> dict:
        if self.port is None:
            raise RuntimeError(f"{self.definition.skill_id} runtime is not started")

        return {
            "type": "http",
            "url": f"http://127.0.0.1:{self.port}/mcp",
        }

    async def close(self) -> None:
        process = self.process

        if process is None:
            return

        if process.stdin is not None:
            process.stdin.write(b"\n")

            try:
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()

        if self.stderr_task is not None:
            await self.stderr_task

        self.process = None
        self.port = None
        self.stderr_task = None


class SkillRegistry:
    def __init__(self, provider_name: str = "claude"):
        browser = SkillDefinition(
            skill_id="browser",
            description=(
                "เปิดเว็บไซต์ ค้นหาเว็บผ่านหน้าต่างเบราว์เซอร์ ปิดแท็บเว็บไซต์ "
                "ดูเว็บไซต์ที่เปิดอยู่ และปิดเบราว์เซอร์ที่ระบบควบคุม"
            ),
            directory=SKILLS_DIR / "browser",
            tool_names=(
                "open_website",
                "search_web",
                "close_tabs",
                "get_open_websites",
                "close_browser",
            ),
        )
        gmail = SkillDefinition(
            skill_id="gmail",
            description=(
                "อ่าน ค้นหา กรอง นับ สรุป และวิเคราะห์อีเมลในกล่องขาเข้า "
                "ผ่าน Gmail API แบบอ่านอย่างเดียว โดยกรองตามช่วงวันที่ "
                "สถานะอ่าน หรือที่อยู่อีเมลผู้ส่งแบบเต็มได้"
            ),
            directory=SKILLS_DIR / "gmail",
            tool_names=("read_emails",),
        )
        calendar = SkillDefinition(
            skill_id="calendar",
            description=(
                "อ่านตารางเวลา นัดหมาย กิจกรรม และช่วงเวลาว่างจาก Google Calendar "
                "รวมถึงเพิ่มกิจกรรมใหม่ในปฏิทินหลักของผู้ใช้"
            ),
            directory=SKILLS_DIR / "calendar",
            tool_names=("read_events", "create_event"),
        )
        youtube = SkillDefinition(
            skill_id="youtube",
            description=(
                "ค้นหาวิดีโอหรือช่องบน YouTube ผ่าน YouTube Data API และเปิดวิดีโอ "
                "ในแท็บใหม่หรือแท็บ YouTube ที่ระบุ หากต้องเลือกแท็บเดิมให้ใช้ร่วมกับ "
                "browser เพื่อดู tab_id ก่อน"
            ),
            directory=SKILLS_DIR / "youtube",
            tool_names=("search_youtube", "open_video"),
            runtime_dependencies=("browser",),
            worker_dependencies=("browser",),
        )
        admin = SkillDefinition(
            skill_id="admin",
            description=(
                "จัดการ ตั้งค่า ตรวจสอบ วินิจฉัย และเปลี่ยนแปลงระบบปฏิบัติการหรือ"
                "โปรแกรมที่ติดตั้ง เช่น ติดตั้ง อัปเดต ซ่อมแซม ตั้งค่า หรือถอนโปรแกรม "
                "ตรวจสอบฮาร์ดแวร์ พื้นที่จัดเก็บ หน่วยความจำ โปรเซส บริการ เครือข่าย "
                "และบันทึกระบบ รวมถึงเรียกใช้คำสั่งหรือสคริปต์เบื้องหลัง ใช้เมื่อคำขอ"
                "ต้องเข้าถึงระบบโดยตรงและไม่มี Skill เฉพาะรองรับ และอย่าใช้ร่วมกับ "
                "Skill อื่นในงานเดียวกัน"
            ),
            directory=None,
            tool_names=(),
        )
        self.central_definitions = {
            browser.skill_id: browser,
            gmail.skill_id: gmail,
            calendar.skill_id: calendar,
            youtube.skill_id: youtube,
            admin.skill_id: admin,
        }
        self.definitions: dict[str, SkillDefinition] = {}
        self.set_provider(provider_name)
        self.runtimes = {
            skill_id: SkillRuntime(definition)
            for skill_id, definition in self.central_definitions.items()
            if definition.tool_names
        }
        browser_bridge_port = self.runtimes["browser"]._find_free_port()
        bridge_environment = {
            "BROWSER_BRIDGE_HOST": "127.0.0.1",
            "BROWSER_BRIDGE_PORT": str(browser_bridge_port),
        }
        self.runtimes["browser"].environment_overrides.update(bridge_environment)
        self.runtimes["youtube"].environment_overrides.update(bridge_environment)

    def set_provider(self, provider_name: str) -> None:
        definitions = {
            skill_id: definition
            for skill_id, definition in self.central_definitions.items()
            if skill_id != "admin"
        }
        if provider_name.strip().casefold() == "claude":
            from claude_skills import claude_skill_definitions

            for definition in claude_skill_definitions():
                definitions[definition.skill_id] = definition
        definitions["admin"] = self.central_definitions["admin"]
        self.definitions = definitions

    async def set_active_user(self, user_id: int | None) -> None:
        users_directory = PROJECT_ROOT / "data" / "users"
        user_directory = users_directory / (
            str(user_id) if user_id is not None else "default"
        )

        browser = self.runtimes["browser"]
        browser_value = str((user_directory / "browser_data").resolve())
        if browser.environment_overrides.get("AIPC_BROWSER_DATA_DIR") != browser_value:
            await browser.close()
            browser.environment_overrides["AIPC_BROWSER_DATA_DIR"] = browser_value

        # Google tokens live directly in the signed-in user's data directory.
        # Without a user no directory is given, so these skills cannot reuse
        # another account's token.
        user_value = str(user_directory.resolve()) if user_id is not None else None
        for skill_id in ("gmail", "calendar"):
            runtime = self.runtimes[skill_id]
            if runtime.environment_overrides.get("AIPC_USER_DATA_DIR") == user_value:
                continue
            await runtime.close()
            if user_value is None:
                runtime.environment_overrides.pop("AIPC_USER_DATA_DIR", None)
            else:
                runtime.environment_overrides["AIPC_USER_DATA_DIR"] = user_value

    def catalog(self) -> str:
        return "\n".join(
            f"- `{definition.skill_id}`: {definition.description}"
            for definition in self.definitions.values()
        )

    def resolve(self, skill_ids: list[str]) -> list[SkillDefinition]:
        unknown = [skill_id for skill_id in skill_ids if skill_id not in self.definitions]

        if unknown:
            raise ValueError("Unknown skill IDs: " + ", ".join(unknown))

        resolved_ids: list[str] = []

        def add_with_dependencies(skill_id: str) -> None:
            if skill_id in resolved_ids:
                return

            resolved_ids.append(skill_id)

            for dependency_id in self.definitions[skill_id].worker_dependencies:
                add_with_dependencies(dependency_id)

        for skill_id in skill_ids:
            add_with_dependencies(skill_id)

        return [self.definitions[skill_id] for skill_id in resolved_ids]

    async def start_runtimes(self, definitions: list[SkillDefinition]) -> None:
        for definition in definitions:
            for dependency_id in definition.runtime_dependencies:
                dependency = self.runtimes[dependency_id]
                await dependency.start()

            runtime = self.runtimes.get(definition.skill_id)

            if runtime is not None:
                await runtime.start()

    def mcp_servers(self, definitions: list[SkillDefinition]) -> dict:
        return {
            definition.skill_id: self.runtimes[definition.skill_id].mcp_config
            for definition in definitions
            if definition.skill_id in self.runtimes
        }

    @asynccontextmanager
    async def _session(self, skill_id: str) -> AsyncIterator[ClientSession]:
        runtime = self.runtimes[skill_id]
        await runtime.start()
        async with streamable_http_client(runtime.mcp_config["url"]) as transport:
            async with ClientSession(transport[0], transport[1]) as session:
                await session.initialize()
                yield session

    async def list_tools(
        self,
        definitions: list[SkillDefinition],
    ) -> list[ToolDefinition]:
        tools: list[ToolDefinition] = []
        for definition in definitions:
            if definition.skill_id not in self.runtimes:
                continue
            async with self._session(definition.skill_id) as session:
                result = await session.list_tools()
                tools.extend(
                    ToolDefinition(
                        skill_id=definition.skill_id,
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.input_schema,
                    )
                    for tool in result.tools
                )
        return tools

    async def call_tool(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._session(tool.skill_id) as session:
            result = await session.call_tool(tool.name, arguments)
            return result.model_dump(mode="json", exclude_none=True)

    async def close(self) -> None:
        for runtime in reversed(list(self.runtimes.values())):
            await runtime.close()
