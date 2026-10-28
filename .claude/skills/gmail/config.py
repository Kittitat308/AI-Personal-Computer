import os
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SKILL_DIR.parents[2]
MCP_HOST = "127.0.0.1"
MCP_PORT = int(os.environ.get("GMAIL_MCP_PORT", "8766"))
_USER_DATA_DIR = os.environ.get("AIPC_USER_DATA_DIR", "").strip()
TOKEN_PATH = (
    Path(_USER_DATA_DIR).resolve() / "gmail_token.json"
    if _USER_DATA_DIR
    else None
)

