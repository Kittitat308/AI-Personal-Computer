import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_DATA_DIR = Path(
    os.environ.get(
        "AIPC_BROWSER_DATA_DIR",
        PROJECT_ROOT / "data" / "users" / "default" / "browser_data",
    )
).resolve()
HEADLESS = False
BROWSER_ARGUMENTS = [
    "--disable-blink-features=AutomationControlled",
]
MCP_HOST = "127.0.0.1"
MCP_PORT = int(os.environ.get("BROWSER_MCP_PORT", "8765"))
BROWSER_BRIDGE_HOST = os.environ.get("BROWSER_BRIDGE_HOST", "127.0.0.1")
BROWSER_BRIDGE_PORT = int(os.environ.get("BROWSER_BRIDGE_PORT", "8875"))
