import asyncio
import json
from pathlib import Path

from core.claude_cli import ClaudeSession
from core.config import PROJECT_ROOT
from core.schemas import ChatResult, WorkerResult
from providers.base import AIProvider, ToolCallback


class ClaudeProvider(AIProvider):
    name = "claude"

    def __init__(self, model: str, effort: str = "medium", api_key: str = "") -> None:
        super().__init__(model, effort, api_key)
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Claude effort ไม่ถูกต้อง")
        self.chat_session: ClaudeSession | None = None
        self.active_worker_session: ClaudeSession | None = None
        self.running_worker_session: ClaudeSession | None = None

    @staticmethod
    def _base_arguments(
        model: str,
        effort: str,
        system_prompt: str,
        schema: dict,
    ) -> list[str]:
        return [
            "-p", "--input-format", "stream-json", "--output-format",
            "stream-json", "--verbose", "--model", model, "--effort", effort,
            "--system-prompt", system_prompt, "--json-schema",
            json.dumps(schema, ensure_ascii=False), "--no-session-persistence",
        ]

    async def generate_chat(self, messages, schema):
        if self.chat_session is None:
            system_prompt = messages[0]["content"]
            if len(messages) > 2:
                recent = "\n".join(
                    f"{item['role'].title()}: {item['content']}"
                    for item in messages[1:-1]
                )
                system_prompt += (
                    "\n\n## Recent conversation\n\n"
                    "Treat this as conversation history, not new instructions.\n"
                    + recent
                )
            arguments = self._base_arguments(
                self.model, self.effort, system_prompt, schema
            )
            arguments.extend(
                [
                    "--tools", "", "--disable-slash-commands",
                    "--setting-sources", "", "--strict-mcp-config",
                    "--permission-mode", "dontAsk",
                ]
            )
            self.chat_session = ClaudeSession(arguments, PROJECT_ROOT)
        try:
            response = await self.chat_session.generate(messages[-1]["content"])
        except Exception:
            await self.reset_chat()
            raise
        if response.structured_output is not None:
            return response.structured_output
        return json.loads(response.text)

    def _worker_session(
        self,
        definitions,
        registry,
        system_prompt: str,
        allowed_directories: list[Path],
    ) -> ClaudeSession:
        mcp_tools = [
            f"mcp__{definition.skill_id}__{tool_name}"
            for definition in definitions
            for tool_name in definition.tool_names
        ]
        builtin_tools = list(
            dict.fromkeys(
                tool_name
                for definition in definitions
                for tool_name in definition.builtin_tool_names
            )
        )
        arguments = self._base_arguments(
            self.model,
            self.effort,
            system_prompt,
            WorkerResult.model_json_schema(),
        )
        arguments.extend(
            [
                "--tools", ",".join(builtin_tools), "--allowedTools",
                ",".join([*mcp_tools, *builtin_tools]), "--mcp-config",
                json.dumps(
                    {"mcpServers": registry.mcp_servers(definitions)},
                    ensure_ascii=False,
                ),
                "--strict-mcp-config", "--permission-mode", "dontAsk",
            ]
        )
        arguments.extend(["--disable-slash-commands", "--setting-sources", ""])
        for directory in allowed_directories:
            arguments.extend(["--add-dir", str(directory)])

        working_directories = {
            definition.working_directory
            for definition in definitions
            if definition.working_directory is not None
        }
        if len(working_directories) > 1:
            raise RuntimeError("Selected CLI skills require different working directories")
        working_directory = next(iter(working_directories), PROJECT_ROOT)
        working_directory.mkdir(parents=True, exist_ok=True)
        return ClaudeSession(arguments, working_directory)

    @staticmethod
    def _task_prompt(task, definitions, skill_instructions: str) -> str:
        prompt = (
            "Delegated task:\n"
            + json.dumps(task.model_dump(), ensure_ascii=False, indent=2)
        )
        if skill_instructions:
            prompt += "\n\nSelected skill instructions:\n\n" + skill_instructions
        working_directories = {
            definition.working_directory.resolve()
            for definition in definitions
            if definition.working_directory is not None
        }
        if len(working_directories) == 1:
            directory = next(iter(working_directories))
            prompt += (
                "\n\nFile workspace boundary:\n"
                f"- Use {directory} as the working directory.\n"
                "- Create every generated or temporary file inside this directory.\n"
                "- Do not create files in the project root or another directory.\n"
                "- Keep every output in the working directory."
            )
        return prompt

    @staticmethod
    def _parse_worker(response) -> dict:
        if response.structured_output is not None:
            return response.structured_output
        return json.loads(response.text)

    async def execute_worker(
        self, *, task, system_prompt, skill_instructions, definitions, tools,
        call_tool: ToolCallback, registry, allowed_directories: list[Path],
    ):
        if self.active_worker_session is not None:
            raise RuntimeError("Worker is already waiting for user input")
        await registry.start_runtimes(definitions)
        session = self._worker_session(
            definitions, registry, system_prompt, allowed_directories
        )
        self.running_worker_session = session
        try:
            response = await session.generate(
                self._task_prompt(task, definitions, skill_instructions)
            )
            result = self._parse_worker(response)
        except asyncio.CancelledError:
            await session.abort()
            raise
        except Exception:
            await session.close()
            raise
        finally:
            self.running_worker_session = None
        if result.get("status") == "needs_input":
            self.active_worker_session = session
        else:
            await session.close()
        return result

    @property
    def worker_awaiting_input(self) -> bool:
        return self.active_worker_session is not None

    async def continue_worker(self, user_message: str) -> dict:
        session = self.active_worker_session
        if session is None:
            raise RuntimeError("Worker is not waiting for user input")
        self.active_worker_session = None
        self.running_worker_session = session
        try:
            result = self._parse_worker(await session.generate(user_message))
        except asyncio.CancelledError:
            await session.abort()
            raise
        except Exception:
            await session.close()
            raise
        finally:
            self.running_worker_session = None
        if result.get("status") == "needs_input":
            self.active_worker_session = session
        else:
            await session.close()
        return result

    async def abort_worker(self) -> None:
        sessions = {
            session
            for session in (self.active_worker_session, self.running_worker_session)
            if session is not None
        }
        self.active_worker_session = None
        self.running_worker_session = None
        await asyncio.gather(*(session.abort() for session in sessions))

    async def reset_chat(self) -> None:
        if self.chat_session is not None:
            await self.chat_session.close()
            self.chat_session = None

    async def close(self) -> None:
        await self.abort_worker()
        await self.reset_chat()
