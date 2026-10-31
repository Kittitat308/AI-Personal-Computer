import asyncio
import json
import os
import socket
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from core.config import CLAUDE_SKILLS_DIR, PROJECT_ROOT, SKILLS_DIR
from providers.catalog import provider_info


@dataclass(frozen=True)
class SkillDefinition:
    """A skill described by the ``skill.json`` in its folder.

    ``requires`` lists skills that always run together with this one,
    ``free_ports`` names environment variables that receive a free port shared
    with the skills that require this one, and ``user_env`` maps environment
    variables to templates filled in with the signed-in user's data directory.
    """

    skill_id: str
    description: str
    directory: Path
    requires: tuple[str, ...] = ()
    builtin_tools: tuple[str, ...] = ()
    working_directory: Path | None = None
    free_ports: tuple[str, ...] = ()
    user_env: dict[str, str] = field(default_factory=dict)
    login_required: bool = False

    @property
    def has_server(self) -> bool:
        return (self.directory / "server.py").is_file()

    @property
    def instructions(self) -> str:
        instruction_file = self.directory / "SKILL.md"
        if not instruction_file.is_file():
            return ""

        return instruction_file.read_text(encoding="utf-8").strip()


def load_definitions(root: Path) -> dict[str, SkillDefinition]:
    definitions: dict[str, SkillDefinition] = {}
    for manifest in sorted(root.glob("*/skill.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        working_directory = data.get("working_directory")
        definitions[manifest.parent.name] = SkillDefinition(
            skill_id=manifest.parent.name,
            description=data["description"],
            directory=manifest.parent,
            requires=tuple(data.get("requires", ())),
            builtin_tools=tuple(data.get("builtin_tools", ())),
            working_directory=(
                PROJECT_ROOT / working_directory if working_directory else None
            ),
            free_ports=tuple(data.get("free_ports", ())),
            user_env=dict(data.get("user_env", {})),
            login_required=bool(data.get("login_required", False)),
        )
    return definitions


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


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

            self.port = find_free_port()
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
        self.central_definitions = load_definitions(SKILLS_DIR)
        self.claude_definitions = load_definitions(CLAUDE_SKILLS_DIR)
        self.definitions: dict[str, SkillDefinition] = {}
        self._session_stack: AsyncExitStack | None = None
        self._open_sessions: dict[str, ClientSession] = {}
        self.set_provider(provider_name)
        self.runtimes = {
            skill_id: SkillRuntime(definition)
            for skill_id, definition in self.central_definitions.items()
            if definition.has_server
        }
        shared_environment = {
            skill_id: {name: str(find_free_port()) for name in definition.free_ports}
            for skill_id, definition in self.central_definitions.items()
        }
        for skill_id, runtime in self.runtimes.items():
            for owner in (*runtime.definition.requires, skill_id):
                runtime.environment_overrides.update(shared_environment[owner])

    def set_provider(self, provider_name: str) -> None:
        definitions = {
            skill_id: definition
            for skill_id, definition in self.central_definitions.items()
            if skill_id != "admin"
        }
        if provider_info(provider_name).claude_skills:
            definitions.update(self.claude_definitions)
        definitions["admin"] = self.central_definitions["admin"]
        self.definitions = definitions

    async def set_active_user(self, user_id: int | None) -> None:
        user_directory = (
            PROJECT_ROOT / "data" / "users" / (str(user_id) if user_id is not None else "default")
        ).resolve()
        for runtime in self.runtimes.values():
            definition = runtime.definition
            if not definition.user_env:
                continue
            # A skill that needs a login gets no directory without a user, so it
            # cannot reuse another account's token.
            values = (
                {}
                if user_id is None and definition.login_required
                else {
                    name: str(Path(template.format(user_dir=user_directory)))
                    for name, template in definition.user_env.items()
                }
            )
            current = {
                name: runtime.environment_overrides.get(name)
                for name in definition.user_env
            }
            if current == {name: values.get(name) for name in definition.user_env}:
                continue
            await runtime.close()
            for name in definition.user_env:
                if name in values:
                    runtime.environment_overrides[name] = values[name]
                else:
                    runtime.environment_overrides.pop(name, None)

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

            for dependency_id in self.definitions[skill_id].requires:
                add_with_dependencies(dependency_id)

        for skill_id in skill_ids:
            add_with_dependencies(skill_id)

        return [self.definitions[skill_id] for skill_id in resolved_ids]

    async def start_runtimes(self, definitions: list[SkillDefinition]) -> None:
        for definition in definitions:
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

    @asynccontextmanager
    async def task_sessions(self) -> AsyncIterator[None]:
        """Keep MCP sessions open for every tool call made inside this block.

        The sessions close in the task that opened them, so a block must not
        span several asyncio tasks.
        """
        try:
            async with AsyncExitStack() as stack:
                self._session_stack = stack
                self._open_sessions = {}
                try:
                    yield
                finally:
                    self._session_stack = None
                    self._open_sessions = {}
        except BaseExceptionGroup as group:
            # The MCP client's task groups wrap any error raised inside this
            # block; surface the original error instead of the wrapper.
            error: BaseException = group
            while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
                error = error.exceptions[0]
            if error is group:
                raise
            raise error from None

    async def _use_session(self, skill_id: str, action):
        if self._session_stack is None:
            async with self._session(skill_id) as session:
                return await action(session)

        session = self._open_sessions.get(skill_id)
        if session is None:
            session = await self._session_stack.enter_async_context(
                self._session(skill_id)
            )
            self._open_sessions[skill_id] = session
        return await action(session)

    async def list_tools(
        self,
        definitions: list[SkillDefinition],
    ) -> list[ToolDefinition]:
        tools: list[ToolDefinition] = []
        for definition in definitions:
            if definition.skill_id not in self.runtimes:
                continue
            result = await self._use_session(
                definition.skill_id, lambda session: session.list_tools()
            )
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
        # Every model gets the same answer for invalid arguments: an error
        # result it can correct, without running the tool.
        validator = jsonschema.validators.validator_for(tool.input_schema)
        problems = [
            problem.message
            for problem in validator(tool.input_schema).iter_errors(arguments)
        ]
        if problems:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Invalid arguments for {tool.name}: "
                        + "; ".join(problems),
                    }
                ],
                "is_error": True,
            }
        result = await self._use_session(
            tool.skill_id, lambda session: session.call_tool(tool.name, arguments)
        )
        return result.model_dump(mode="json", exclude_none=True)

    async def close(self) -> None:
        for runtime in reversed(list(self.runtimes.values())):
            await runtime.close()
