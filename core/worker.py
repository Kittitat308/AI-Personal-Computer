import asyncio
import json

from core.claude_cli import ClaudeSession
from core.config import MODEL, PROJECT_ROOT, PROMPTS_DIR
from core.schemas import TaskRequest, WorkerResult
from core.skill_registry import SkillDefinition, SkillRegistry


CLI_SKILLS = (
    "browser",
    "calendar",
    "gmail",
    "web_research",
    "youtube",
    "deep-research",
    "design",
    "design-sync",
    "dataviz",
    "update-config",
    "verify",
    "debug",
    "code-review",
    "simplify",
    "batch",
    "fewer-permission-prompts",
    "doctor",
    "loop",
    "schedule",
    "claude-api",
    "workflow-authoring",
    "run",
    "run-skill-generator",
    "plugin-authoring",
    "docs",
    "docx",
    "google-workspace",
    "import-memory",
    "morning",
    "pdf",
    "pptx",
    "skill-creator",
    "xlsx",
)

SYNCED_SKILL_NAMESPACE = "anthropic-skills"


class WorkerAI:
    def __init__(self, registry: SkillRegistry, model: str = MODEL):
        self.registry = registry
        self.model = model
        self.system_prompt = (PROMPTS_DIR / "worker.md").read_text(encoding="utf-8")
        self.active_session = None
        self.running_session = None

    @property
    def awaiting_user_input(self) -> bool:
        return self.active_session is not None

    def _create_session(
        self,
        definitions: list[SkillDefinition],
        mcp_servers: dict,
    ) -> ClaudeSession:
        schema = json.dumps(WorkerResult.model_json_schema(), ensure_ascii=False)
        config = json.dumps({"mcpServers": mcp_servers}, ensure_ascii=False)
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
        allowed_tools = ",".join([*mcp_tools, *builtin_tools])
        slash_definitions = [
            definition for definition in definitions if definition.slash_command
        ]
        working_directories = {
            definition.working_directory
            for definition in slash_definitions
            if definition.working_directory is not None
        }

        if len(working_directories) > 1:
            raise RuntimeError("Selected CLI skills require different working directories")

        working_directory = next(iter(working_directories), PROJECT_ROOT)
        working_directory.mkdir(parents=True, exist_ok=True)
        arguments = [
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--system-prompt",
            self.system_prompt.strip(),
            "--json-schema",
            schema,
            "--tools",
            ",".join(builtin_tools),
            "--allowedTools",
            allowed_tools,
            "--mcp-config",
            config,
            "--strict-mcp-config",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
        ]

        if slash_definitions:
            settings = self._cli_skill_settings(slash_definitions)
            arguments.extend(
                [
                    "--setting-sources",
                    "user,project",
                    "--settings",
                    json.dumps(settings, ensure_ascii=False),
                ]
            )
        else:
            arguments.extend(
                [
                    "--disable-slash-commands",
                    "--setting-sources",
                    "project",
                ]
            )

        return ClaudeSession(arguments, working_directory)

    def _cli_skill_settings(
        self,
        definitions: list[SkillDefinition],
    ) -> dict:
        overrides = {skill_name: "off" for skill_name in CLI_SKILLS}
        overrides.update(
            {
                f"{SYNCED_SKILL_NAMESPACE}:{skill_name}": "off"
                for skill_name in CLI_SKILLS
            }
        )

        for definition in definitions:
            skill_name = definition.slash_command

            if skill_name is None:
                continue

            overrides[skill_name] = "user-invocable-only"
            overrides[
                f"{SYNCED_SKILL_NAMESPACE}:{skill_name}"
            ] = "user-invocable-only"

        return {"skillOverrides": overrides}

    def _task_prompt(
        self,
        task: TaskRequest,
        definitions: list[SkillDefinition],
    ) -> str:
        skill_sections = "\n\n".join(
            f"## Skill: {definition.skill_id}\n\n{definition.instructions}"
            for definition in definitions
            if definition.instructions
        )
        prompt = (
            "Delegated task:\n"
            + json.dumps(task.model_dump(), ensure_ascii=False, indent=2)
        )

        if skill_sections:
            prompt += "\n\nSelected skill instructions:\n\n" + skill_sections

        slash_commands = [
            f"/{definition.slash_command}"
            for definition in definitions
            if definition.slash_command
        ]

        if slash_commands:
            prompt = " ".join(slash_commands) + "\n\n" + prompt

        working_directories = {
            definition.working_directory.resolve()
            for definition in definitions
            if definition.working_directory is not None
        }
        if len(working_directories) == 1:
            working_directory = next(iter(working_directories))
            prompt += (
                "\n\nFile workspace boundary:\n"
                f"- Use {working_directory} as the working directory.\n"
                "- Create every generated or temporary file inside this directory.\n"
                "- Do not create files in the project root or another directory.\n"
                "- A user-selected additional directory may be read only when the task "
                "requires an existing file from it; keep all outputs in the working directory.\n"
                "- After completing the task, respond with only one short natural sentence "
                "stating that the requested file was created or edited, including the "
                "filename and subject when useful. Do not describe the document contents, "
                "formatting, validation process, temporary files, or working directory."
            )

        return prompt

    async def execute(self, task: TaskRequest) -> WorkerResult:
        if self.active_session is not None:
            raise RuntimeError("Worker is already waiting for user input")

        task = TaskRequest.model_validate(task)
        definitions = self.registry.resolve(task.skill_ids)
        await self.registry.start_runtimes(definitions)
        session = self._create_session(definitions, self.registry.mcp_servers(definitions))
        self.running_session = session

        try:
            response = await session.generate(self._task_prompt(task, definitions))
            result = self._parse_result(response.structured_output, response.text)
        except asyncio.CancelledError:
            await session.abort()
            raise
        except Exception:
            await session.close()
            raise
        finally:
            if self.running_session is session:
                self.running_session = None

        if result.status == "needs_input":
            self.active_session = session
        else:
            await session.close()

        return result

    async def continue_with_user_input(self, user_message: str) -> WorkerResult:
        if self.active_session is None:
            raise RuntimeError("Worker is not waiting for user input")

        session = self.active_session
        self.running_session = session
        try:
            response = await session.generate(
                "The user answered your question:\n"
                + user_message.strip()
                + "\n\nContinue the same delegated task."
            )
        except asyncio.CancelledError:
            self.active_session = None
            await session.abort()
            raise
        finally:
            if self.running_session is session:
                self.running_session = None
        result = self._parse_result(response.structured_output, response.text)

        if result.status != "needs_input":
            await self.active_session.close()
            self.active_session = None

        return result

    def _parse_result(self, structured_output, text: str) -> WorkerResult:
        if structured_output is not None:
            return WorkerResult.model_validate(structured_output)

        try:
            return WorkerResult.model_validate_json(text)
        except Exception as error:
            raise RuntimeError(f"Worker returned invalid structured output: {error}") from error

    async def close(self) -> None:
        if self.active_session is not None:
            await self.active_session.close()

        self.active_session = None

    async def abort(self) -> None:
        sessions = {
            session
            for session in (self.running_session, self.active_session)
            if session is not None
        }
        self.running_session = None
        self.active_session = None
        if sessions:
            await asyncio.gather(
                *(session.abort() for session in sessions),
                return_exceptions=True,
            )
