#!/usr/bin/python3
"""Expose the active seat0 Wayland display to the machine's Pi Connect account."""

from __future__ import annotations

import os
import pwd
import stat
import subprocess
import time
from pathlib import Path


CONNECT_USER = "mark"
POLL_SECONDS = 1.0


def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def active_wayland_socket(connect_uid: int) -> tuple[Path, int] | None:
    candidates: list[tuple[int, int, Path, int]] = []
    for runtime in Path("/run/user").glob("[0-9]*"):
        try:
            uid = int(runtime.name)
        except ValueError:
            continue
        if uid == connect_uid:
            continue
        # A real user's desktop wins over LightDM. Among equal candidates, use
        # the newest socket so a newly started session replaces a stale one.
        priority = 2 if uid >= 1000 else 1 if uid == 104 else 0
        if priority == 0:
            continue
        for name in ("wayland-0", "wayland-1"):
            candidate = runtime / name
            try:
                info = candidate.stat()
            except (FileNotFoundError, PermissionError):
                continue
            if stat.S_ISSOCK(info.st_mode):
                candidates.append((priority, info.st_mtime_ns, candidate, uid))
    if not candidates:
        return None
    _, _, path, uid = max(candidates, key=lambda item: (item[0], item[1]))
    return path, uid


def restart_wayvnc(connect_uid: int) -> None:
    run([
        "/usr/sbin/runuser",
        "-u",
        CONNECT_USER,
        "--",
        "/usr/bin/env",
        f"XDG_RUNTIME_DIR=/run/user/{connect_uid}",
        "/usr/bin/systemctl",
        "--user",
        "restart",
        "rpi-connect-wayvnc.service",
    ])


def bridge(target: Path, target_uid: int, connect_uid: int) -> bool:
    connect_runtime = Path("/run/user") / str(connect_uid)
    link = connect_runtime / "wayland-0"
    if target_uid == connect_uid and target == link:
        return False
    if not connect_runtime.is_dir():
        return False

    run(["/usr/bin/setfacl", "-m", f"u:{CONNECT_USER}:--x", str(target.parent)])
    run(["/usr/bin/setfacl", "-m", f"u:{CONNECT_USER}:rw", str(target)])

    if link.is_symlink() and os.path.realpath(link) == str(target):
        return False
    if link.exists() and not link.is_symlink():
        return False
    link.unlink(missing_ok=True)
    link.symlink_to(target)
    restart_wayvnc(connect_uid)
    return True


def main() -> None:
    connect_uid = pwd.getpwnam(CONNECT_USER).pw_uid
    while True:
        try:
            selected = active_wayland_socket(connect_uid)
            if selected is not None:
                target, target_uid = selected
                if bridge(target, target_uid, connect_uid):
                    print(f"Pi Connect now follows {target}", flush=True)
        except Exception as error:
            print(f"Pi Connect bridge error: {error}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
