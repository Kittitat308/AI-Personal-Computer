import asyncio
import json

from core.claude_cli import ClaudeSession
from core.config import CONFIRMATION_MODEL, PROJECT_ROOT, PROMPTS_DIR
from core.schemas import ConfirmationResult


class ConfirmationAI:
    """One isolated, tool-free CLI session per permission response."""

    def __init__(self, model: str = CONFIRMATION_MODEL):
        self.model = model
        self.system_prompt = (PROMPTS_DIR / "confirmation.md").read_text(
            encoding="utf-8"
        )

    def _create_session(self) -> ClaudeSession:
        schema = json.dumps(
            ConfirmationResult.model_json_schema(),
            ensure_ascii=False,
        )
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
            "",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--permission-mode",
            "dontAsk",
            "--setting-sources",
            "",
            "--no-session-persistence",
        ]
        return ClaudeSession(arguments, PROJECT_ROOT)

    async def classify(
        self,
        permission_question: str,
        user_response: str,
    ) -> str:
        session = self._create_session()
        prompt = (
            "Permission question:\n"
            + permission_question.strip()
            + "\n\nUser response:\n"
            + user_response.strip()
        )
        try:
            response = await session.generate(prompt)
            if response.structured_output is not None:
                result = ConfirmationResult.model_validate(
                    response.structured_output
                )
            else:
                result = ConfirmationResult.model_validate_json(response.text)
            return result.decision
        except asyncio.CancelledError:
            await session.abort()
            raise
        finally:
            await session.close()
