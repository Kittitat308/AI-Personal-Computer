import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"
DOCUMENTS_DIR = Path(
    os.environ.get("AIPC_DOCUMENTS_DIR", PROJECT_ROOT / "documents")
).resolve()

MODEL = "haiku"
CONFIRMATION_MODEL = "haiku"
ADMIN_MODEL = "claude-opus-5-5"
ADMIN_EFFORT = "medium"
CHAT_SESSION_TURN_LIMIT = 10
CHAT_RECENT_TURNS_TO_KEEP = 3


def validate_session_settings() -> None:
    if CHAT_SESSION_TURN_LIMIT < 1:
        raise ValueError("CHAT_SESSION_TURN_LIMIT must be at least 1")

    if not 0 <= CHAT_RECENT_TURNS_TO_KEEP < CHAT_SESSION_TURN_LIMIT:
        raise ValueError(
            "CHAT_RECENT_TURNS_TO_KEEP must be at least 0 and smaller than "
            "CHAT_SESSION_TURN_LIMIT"
        )
