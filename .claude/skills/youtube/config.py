import os
from pathlib import Path

from dotenv import load_dotenv


SKILL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SKILL_DIR.parents[2]
ENV_FILE = Path(os.environ.get("AIPC_ENV_FILE", PROJECT_ROOT / ".env"))
load_dotenv(ENV_FILE)

MCP_HOST = "127.0.0.1"
MCP_PORT = int(os.environ.get("YOUTUBE_MCP_PORT", "8768"))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
BROWSER_BRIDGE_HOST = os.environ.get("BROWSER_BRIDGE_HOST", "127.0.0.1")
BROWSER_BRIDGE_PORT = int(os.environ.get("BROWSER_BRIDGE_PORT", "8875"))
