import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
SKILLS_DIR = PROJECT_ROOT / "skills"
CLAUDE_SKILLS_DIR = PROJECT_ROOT / "claude_skills"
MODELS_DIR = PROJECT_ROOT / "models"

load_dotenv(PROJECT_ROOT / ".env", override=True)

RUN_AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").strip().casefold()
RUN_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
RUN_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
RUN_CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku").strip()
RUN_MODEL_EFFORT = os.getenv("MODEL_EFFORT", "medium").strip().casefold()
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
