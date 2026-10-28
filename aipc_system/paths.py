import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("AIPC_STATE_DIR", "/var/lib/ai-personal-computer"))
RUNTIME_DIR = Path(os.environ.get("AIPC_RUNTIME_DIR", "/run/ai-personal-computer"))
AUTH_DATABASE = STATE_DIR / "database" / "auth.db"
AUTH_SOCKET = RUNTIME_DIR / "auth.sock"
ACCOUNT_HELPER_SOCKET = Path("/run/aipc-account-helper.sock")
FACE_TOKEN_DIR = RUNTIME_DIR / "face-auth"
SHARED_CLAUDE_DIR = Path("/var/lib/aipc-ai")
SYSTEM_SECRETS_DIR = Path("/etc/ai-personal-computer")


def user_data_dir(home: Path | None = None) -> Path:
    resolved_home = home or Path.home()
    return resolved_home / ".local" / "share" / "ai-personal-computer"


def user_config_dir(home: Path | None = None) -> Path:
    resolved_home = home or Path.home()
    return resolved_home / ".config" / "ai-personal-computer"


def user_documents_dir(home: Path | None = None) -> Path:
    resolved_home = home or Path.home()
    return resolved_home / "Documents" / "AI Personal Computer"
