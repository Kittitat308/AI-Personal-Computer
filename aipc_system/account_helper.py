#!/opt/ai-personal-computer/.venv/bin/python
"""Narrow root helper. It never executes caller-provided commands or paths."""

import grp
import json
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path


USERNAME = re.compile(r"^[a-z][a-z0-9]{0,31}$")
PASSWORD = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9]{8,}$")


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    raise SystemExit(1)


def validate_username(value: object) -> str:
    username = str(value or "")
    if USERNAME.fullmatch(username) is None:
        fail("ชื่อผู้ใช้ไม่ถูกต้อง")
    return username


def validate_password(value: object) -> str:
    password = str(value or "")
    if PASSWORD.fullmatch(password) is None:
        fail("รหัสผ่านไม่ถูกต้อง")
    return password


def run(arguments: list[str], input_text: str | None = None) -> None:
    completed = subprocess.run(
        arguments,
        input=input_text,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        fail(completed.stderr.strip() or "คำสั่งระบบล้มเหลว")


def prepare_home(username: str) -> None:
    account = pwd.getpwnam(username)
    home = Path(account.pw_dir)
    paths = (
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / ".config" / "ai-personal-computer",
        home / ".local" / "share" / "ai-personal-computer" / "browser-data",
        home / ".local" / "share" / "ai-personal-computer" / "google",
        home / "Documents" / "AI Personal Computer",
    )
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    run(["/usr/bin/chown", "-R", f"{account.pw_uid}:{account.pw_gid}", str(home)])
    # Claude runs through the dedicated, non-login aipc-ai account. ACLs let
    # that account work only inside the selected user's home; bubblewrap hides
    # every other home for each invocation.
    try:
        pwd.getpwnam("aipc-ai")
    except KeyError:
        fail("ไม่พบบัญชีบริการ AI กลาง")
    run([
        "/usr/bin/setfacl", "-R", "-m", "u:aipc-ai:rwx", "-m", "d:u:aipc-ai:rwx",
        str(home),
    ])


def create(data: dict) -> None:
    username = validate_username(data.get("username"))
    password = validate_password(data.get("password"))
    nickname = str(data.get("nickname") or "").strip()
    if not nickname or len(nickname) > 128 or any(ord(char) < 32 for char in nickname):
        fail("ชื่อเล่นไม่ถูกต้อง")
    try:
        pwd.getpwnam(username)
    except KeyError:
        pass
    else:
        fail("ชื่อผู้ใช้นี้มีอยู่ในระบบแล้ว")

    run([
        "/usr/sbin/useradd",
        "--create-home",
        "--shell", "/bin/bash",
        "--comment", nickname,
        username,
    ])
    try:
        run(["/usr/sbin/chpasswd"], f"{username}:{password}\n")
        available = {item.gr_name for item in grp.getgrall()}
        groups = [
            name
            for name in (
                "aipc-users", "aipc-runtime", "audio", "video", "render", "input"
            )
            if name in available
        ]
        if groups:
            run(["/usr/sbin/usermod", "-a", "-G", ",".join(groups), username])
        prepare_home(username)
    except BaseException:
        subprocess.run(
            ["/usr/sbin/userdel", "--remove", username],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        raise


def rollback_create(data: dict) -> None:
    username = validate_username(data.get("username"))
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        return
    if account.pw_uid < 1000:
        fail("ไม่สามารถลบบัญชีระบบได้")
    run(["/usr/sbin/userdel", "--remove", username])


def set_password(data: dict) -> None:
    username = validate_username(data.get("username"))
    password = validate_password(data.get("password"))
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        fail("ไม่พบบัญชี Linux")
    if account.pw_uid < 1000:
        fail("ไม่สามารถแก้รหัสผ่านบัญชีระบบได้")
    run(["/usr/sbin/chpasswd"], f"{username}:{password}\n")


def power(operation: str) -> None:
    os.sync()
    subprocess.Popen(
        ["/usr/bin/systemctl", operation],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> None:
    if os.geteuid() != 0:
        fail("ตัวช่วยต้องทำงานด้วยสิทธิ์ root")
    raw = sys.stdin.buffer.readline(65537)
    if not raw or len(raw) > 65536:
        fail("คำขอไม่ถูกต้อง")
    request = json.loads(raw.decode("utf-8"))
    operation = str(request.get("operation") or "")
    data = request.get("data") or {}
    handlers = {
        "create": create,
        "rollback-create": rollback_create,
        "set-password": set_password,
        "reboot": lambda _data: power("reboot"),
        "poweroff": lambda _data: power("poweroff"),
    }
    handler = handlers.get(operation)
    if handler is None:
        fail("ไม่อนุญาตคำสั่งนี้")
    handler(data)
    print(json.dumps({"ok": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
