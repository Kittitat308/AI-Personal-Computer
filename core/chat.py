from collections import deque
from dataclasses import dataclass
from pathlib import Path

from core.config import (
    CHAT_RECENT_TURNS_TO_KEEP,
    CHAT_SESSION_TURN_LIMIT,
    PROMPTS_DIR,
    validate_session_settings,
)
from core.schemas import ChatResult
from providers.base import AIProvider


@dataclass
class ConversationTurn:
    user: str
    assistant: str


class ChatAI:
    def __init__(
        self,
        provider: AIProvider,
        skill_catalog: str,
        turn_limit: int = CHAT_SESSION_TURN_LIMIT,
        recent_turns_to_keep: int = CHAT_RECENT_TURNS_TO_KEEP,
    ):
        validate_session_settings()
        self.provider = provider
        self.turn_limit = turn_limit
        self.recent_turns_to_keep = recent_turns_to_keep
        self.skill_catalog = skill_catalog
        self.base_prompt = (PROMPTS_DIR / "chat.md").read_text(encoding="utf-8")
        self.turn_count = 0
        self.history: deque[ConversationTurn] = deque(maxlen=turn_limit)

    def _system_prompt(self) -> str:
        return "\n\n".join(
            [
                self.base_prompt.strip(),
                "## Available skills\n\n" + self.skill_catalog.strip(),
            ]
        )

    def _messages(self, current_content) -> list[dict]:
        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt()}
        ]
        for turn in self.history:
            messages.extend(
                [
                    {"role": "user", "content": turn.user},
                    {"role": "assistant", "content": turn.assistant},
                ]
            )
        messages.append({"role": "user", "content": current_content})
        return messages

    async def generate(
        self,
        user_message: str,
        previous_execution_result: str | None = None,
        attachments: list[Path] | None = None,
    ) -> ChatResult:
        prompt = user_message.strip()
        if previous_execution_result:
            prompt = (
                "Previous execution result:\n"
                + previous_execution_result.strip()
                + "\n\nCurrent user message:\n"
                + prompt
            )

        attachment_paths = attachments or []
        message_content = self.provider.user_content(prompt, attachment_paths)

        try:
            raw = await self.provider.generate_chat(
                self._messages(message_content),
                ChatResult.model_json_schema(),
            )
        except Exception:
            await self.provider.reset_chat()
            raise
        result = ChatResult.model_validate(raw)
        history_message = user_message.strip()
        if attachment_paths:
            filenames = ", ".join(path.name for path in attachment_paths)
            history_message += f" [ไฟล์แนบ: {filenames}]"
        self.history.append(
            ConversationTurn(user=history_message, assistant=result.response)
        )
        self.turn_count += 1
        return result

    def record_worker_result(self, response: str) -> None:
        if self.history:
            self.history[-1].assistant = response.strip()

    def record_worker_continuation(self, user_message: str, response: str) -> None:
        self.history.append(
            ConversationTurn(user=user_message.strip(), assistant=response.strip())
        )

    @property
    def rotation_due(self) -> bool:
        return self.turn_count >= self.turn_limit

    async def rotate_if_due(self) -> bool:
        if not self.rotation_due:
            return False
        retained = list(self.history)[-self.recent_turns_to_keep :]
        await self.provider.reset_chat()
        self.history = deque(retained, maxlen=self.turn_limit)
        self.turn_count = 0
        return True

    async def reset(self) -> None:
        await self.provider.reset_chat()
        self.history.clear()
        self.turn_count = 0

    async def close(self) -> None:
        await self.provider.reset_chat()
