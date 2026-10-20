import os
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SKILL_DIR.parents[2]
MCP_HOST = "127.0.0.1"
MCP_PORT = int(os.environ.get("CALENDAR_MCP_PORT", "8767"))

