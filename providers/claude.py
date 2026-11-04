import json
from pathlib import Path

from core.attachments import build_user_content
from core.claude_cli import (
    HOST_PERMISSION_PROMPTS,
    ISOLATED_ARGUMENTS,
    ISOLATED_SETTINGS,
    ClaudeSession,
    InteractiveSession,
    stream_json_arguments,
)
from core.config import PROJECT_ROOT
from core.schemas import WorkerResult
from providers.base import AIProvider, Workspace
from providers.catalog import DEFAULT_EFFORT, PROVIDERS


# Tools that never change anything, so they run without asking.
READ_ONLY_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch"}


class ClaudeProvider(AIProvider):
    name = "claude"

    def __init__(self, model: str, effort: str = DEFAULT_EFFORT, api_key: str = "") -> None:
        super().__init__(model, effort, api_key)
        if effort not in {value for _, value in PROVIDERS[self.name].efforts}:
            raise ValueError("Claude effort ไม่ถูกต้อง")
        self.chat_session: ClaudeSession | None = None
        self.worker_session: InteractiveSession | None = None
        self.worker_waiting = False

    def _base_arguments(self, system_prompt: str, schema: dict) -> list[str]:
        return stream_json_arguments(
            model=self.model,
            effort=self.effort,
            system_prompt=system_prompt,
            schema=schema,
        )

    def user_content(self, prompt: str, attachments: list[Path]):
        if not attachments:
            return prompt
        return build_user_content(prompt, attachments)

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
            arguments = self._base_arguments(system_prompt, schema)
            arguments.extend(["--tools", "", *ISOLATED_ARGUMENTS])
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
        workspace: Workspace,
    ) -> ClaudeSession:
        mcp_tools = [
            f"mcp__{definition.skill_id}"
            for definition in definitions
            if definition.has_server
        ]
        builtin_tools = list(
            dict.fromkeys(
                tool_name
                for definition in definitions
                for tool_name in definition.builtin_tools
            )
        )
        # Like Claude Code: reading is free, while changes follow the
        # permission mode and ask the user through the host when needed.
        allowed_tools = [
            *mcp_tools,
            *(tool for tool in builtin_tools if tool in READ_ONLY_TOOLS),
        ]
        arguments = self._base_arguments(
            system_prompt, WorkerResult.model_json_schema()
        )
        arguments.extend(
            [
                "--tools", ",".join(builtin_tools),
                "--allowedTools", ",".join(allowed_tools),
                "--mcp-config",
                json.dumps(
                    {"mcpServers": registry.mcp_servers(definitions)},
                    ensure_ascii=False,
                ),
                *ISOLATED_SETTINGS,
                # The user's own folder asks before every change (Claude
                # Code's default mode); a temporary output folder accepts
                # edits inside it and still asks for anything else.
                "--permission-mode",
                "manual" if workspace.user_folder else "acceptEdits",
                *HOST_PERMISSION_PROMPTS,
            ]
        )
        for directory in workspace.extra_directories:
            arguments.extend(["--add-dir", str(directory)])
        return ClaudeSession(arguments, workspace.directory)

    @staticmethod
    def _task_prompt(task, skill_instructions: str, workspace: Workspace) -> str:
        prompt = (
            "Delegated task:\n"
            + json.dumps(task.model_dump(), ensure_ascii=False, indent=2)
        )
        if skill_instructions:
            prompt += "\n\nSelected skill instructions:\n\n" + skill_instructions
        if workspace.user_folder:
            prompt += (
                "\n\nWorking folder:\n"
                f"- The user selected {workspace.directory} as the folder to work in.\n"
                "- Work on the files in this folder and save new files here.\n"
                "- Change or delete only what the task requires."
            )
        else:
            prompt += (
                "\n\nOutput folder:\n"
                f"- Save every file made for the user in {workspace.directory}.\n"
                "- Every file left in this folder is sent to the user as an "
                "attachment, so remove scratch files before finishing.\n"
                "- Files saved anywhere else are not delivered."
            )
        return prompt

    @staticmethod
    def _parse_worker(response) -> dict:
        if response.structured_output is not None:
            return response.structured_output
        return json.loads(response.text)

    async def execute_worker(
        self, *, task, system_prompt, skill_instructions, definitions, registry,
        workspace: Workspace,
    ):
        if self.worker_session is not None:
            raise RuntimeError("Worker is already handling a task")
        await registry.start_runtimes(definitions)
        self.worker_session = InteractiveSession(
            self._worker_session(definitions, registry, system_prompt, workspace)
        )
        self.worker_session.start_turn(
            self._task_prompt(task, skill_instructions, workspace)
        )
        return await self._wait_worker()

    async def _wait_worker(self) -> dict:
        session = self.worker_session
        try:
            response = await session.wait()
            if response is None:
                self.worker_waiting = True
                return {"status": "needs_input", "response": session.question}
            result = self._parse_worker(response)
        except BaseException:
            await self.abort_worker()
            raise
        if result.get("status") == "needs_input":
            self.worker_waiting = True
        else:
            self.worker_session = None
            await session.close()
        return result

    @property
    def worker_awaiting_input(self) -> bool:
        return self.worker_waiting

    @property
    def worker_pending_permission(self) -> dict | None:
        if self.worker_session is None:
            return None
        return self.worker_session.pending_permission

    @property
    def worker_permission_question(self) -> str:
        if self.worker_session is None:
            raise RuntimeError("Worker is not waiting for a permission decision")
        return self.worker_session.question

    async def continue_worker(self, user_message: str) -> dict:
        if not self.worker_waiting or self.worker_pending_permission is not None:
            raise RuntimeError("Worker is not waiting for an answer")
        self.worker_waiting = False
        self.worker_session.start_turn(user_message)
        return await self._wait_worker()

    async def answer_worker_permission(self, allow: bool) -> dict:
        if self.worker_pending_permission is None:
            raise RuntimeError("Worker is not waiting for a permission decision")
        self.worker_waiting = False
        await self.worker_session.answer_permission(allow)
        return await self._wait_worker()

    async def abort_worker(self) -> None:
        session, self.worker_session = self.worker_session, None
        self.worker_waiting = False
        if session is not None:
            await session.abort()

    async def reset_chat(self) -> None:
        if self.chat_session is not None:
            await self.chat_session.close()
            self.chat_session = None

    async def close(self) -> None:
        await self.abort_worker()
        await self.reset_chat()
