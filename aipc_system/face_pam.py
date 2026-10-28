#!/opt/ai-personal-computer/.venv/bin/python
import os
import re
import sys
import time
from pathlib import Path


USERNAME = re.compile(r"^[a-z][a-z0-9]{0,31}$")
TOKEN_DIRECTORY = Path("/run/ai-personal-computer/face-auth")


def main() -> int:
    username = os.environ.get("PAM_USER", "")
    if USERNAME.fullmatch(username) is None:
        return 1
    token = TOKEN_DIRECTORY / username
    try:
        stat = token.stat()
        if not token.is_file() or time.time() - stat.st_mtime > 15:
            return 1
        if stat.st_mode & 0o077:
            return 1
        token.unlink()
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
