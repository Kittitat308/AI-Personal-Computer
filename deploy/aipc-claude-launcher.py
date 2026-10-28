#!/usr/bin/python3
import os
import pwd
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    caller = os.environ.get("SUDO_USER", "")
    if not caller or caller in {"root", "aipc-ai", "aipc-auth", "lightdm"}:
        fail("ไม่อนุญาตให้เรียก Claude launcher")
    try:
        account = pwd.getpwnam(caller)
    except KeyError:
        fail("ไม่พบบัญชีผู้ใช้")
    if account.pw_uid < 1000:
        fail("ไม่อนุญาตบัญชีระบบ")

    home = Path(account.pw_dir).resolve()
    cwd = Path.cwd().resolve()
    project = Path("/opt/ai-personal-computer")
    if cwd != project and home not in cwd.parents and cwd != home:
        fail("ตำแหน่งทำงานอยู่นอกพื้นที่ที่อนุญาต")

    claude_home = Path("/var/lib/aipc-ai")
    claude_config = claude_home / ".claude"
    sandbox_config = "/tmp/claude-config"
    arguments = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--ro-bind", "/", "/",
        "--dev-bind", "/dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/home",
        "--dir", str(home),
        "--bind", str(home), str(home),
        "--tmpfs", "/tmp",
        "--dir", sandbox_config,
        "--bind", str(claude_config), sandbox_config,
        "--chdir", str(cwd),
        "--setenv", "HOME", str(home),
        "--setenv", "USER", caller,
        "--setenv", "LOGNAME", caller,
        "--setenv", "CLAUDE_CONFIG_DIR", sandbox_config,
        "/usr/local/bin/claude",
        *sys.argv[1:],
    ]
    os.execv(arguments[0], arguments)


if __name__ == "__main__":
    main()
