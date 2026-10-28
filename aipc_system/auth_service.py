import base64
import json
import os
import pwd
import re
import secrets
import socket
import socketserver
import struct
from pathlib import Path

import numpy as np

from aipc_system.account_manager import AccountManager
from aipc_system.paths import AUTH_SOCKET, FACE_TOKEN_DIR, RUNTIME_DIR


LIGHTDM_USER = "lightdm"
USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,31}$")


def _serialize_user(user):
    if user is None:
        return None
    return {"id": user.id, "username": user.username, "nickname": user.nickname}


class AuthorizationError(PermissionError):
    pass


class AuthRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(1024 * 1024)
        try:
            request = json.loads(raw.decode("utf-8"))
            result = self.server.dispatch(self.request, request)
            response = {"ok": True, "result": result}
        except Exception as error:
            response = {
                "ok": False,
                "error": str(error) or error.__class__.__name__,
                "error_type": error.__class__.__name__,
            }
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


class AuthServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: Path = AUTH_SOCKET):
        self.socket_path = socket_path
        self.manager = AccountManager()
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.exists():
            socket_path.unlink()
        super().__init__(str(socket_path), AuthRequestHandler)
        os.chmod(socket_path, 0o666)

    @staticmethod
    def _peer_identity(connection: socket.socket) -> tuple[int, str]:
        _pid, uid, _gid = struct.unpack(
            "3i",
            connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12),
        )
        try:
            username = pwd.getpwuid(uid).pw_name
        except KeyError:
            username = ""
        return uid, username

    @staticmethod
    def _require_greeter_or_root(uid: int, username: str) -> None:
        if uid != 0 and username != LIGHTDM_USER:
            raise AuthorizationError("คำสั่งนี้ใช้ได้เฉพาะหน้าเข้าสู่ระบบ")

    def _current_app_user(self, uid: int, linux_username: str):
        if uid == 0:
            raise AuthorizationError("ต้องระบุผู้ใช้ผ่านหน้าเข้าสู่ระบบ")
        user = self.manager.database.get_user_by_username(linux_username)
        if user is None:
            raise AuthorizationError("บัญชี Linux นี้ไม่ได้เชื่อมกับระบบ")
        return user

    def dispatch(self, connection: socket.socket, request: dict):
        uid, peer_username = self._peer_identity(connection)
        action = str(request.get("action", ""))
        data = request.get("data") or {}

        if action == "health":
            return {"status": "ok"}

        if action == "create_user":
            self._require_greeter_or_root(uid, peer_username)
            embeddings = [
                np.frombuffer(base64.b64decode(value), dtype=np.float32).copy()
                for value in data.get("embeddings", [])
            ]
            user = self.manager.create_user(
                str(data.get("username", "")),
                str(data.get("nickname", "")),
                str(data.get("password", "")),
                embeddings,
                str(data.get("recovery_gmail", "")),
                bool(data.get("recovery_gmail_verified", False)),
            )
            return _serialize_user(user)

        if action == "authenticate":
            self._require_greeter_or_root(uid, peer_username)
            return _serialize_user(
                self.manager.database.authenticate(
                    str(data.get("username", "")),
                    str(data.get("password", "")),
                )
            )

        if action == "get_user_by_verified_recovery_gmail":
            self._require_greeter_or_root(uid, peer_username)
            return _serialize_user(
                self.manager.database.get_user_by_verified_recovery_gmail(
                    str(data.get("gmail", ""))
                )
            )

        if action == "recovery_gmail_in_use_public":
            self._require_greeter_or_root(uid, peer_username)
            return self.manager.database.recovery_gmail_in_use(
                str(data.get("gmail", ""))
            )

        if action == "reset_password_for_user":
            self._require_greeter_or_root(uid, peer_username)
            self.manager.reset_password(
                int(data.get("user_id")),
                str(data.get("new", "")),
            )
            return True

        if action == "list_face_profiles":
            if uid == 0 or peer_username == LIGHTDM_USER:
                profiles = self.manager.database.list_face_profiles()
            else:
                current = self._current_app_user(uid, peer_username)
                profiles = [
                    (user, embedding)
                    for user, embedding in self.manager.database.list_face_profiles()
                    if user.id == current.id
                ]
            result = []
            for user, embedding in profiles:
                result.append(
                    {
                        "user": _serialize_user(user),
                        "embedding": base64.b64encode(
                            np.asarray(embedding, dtype=np.float32).tobytes()
                        ).decode("ascii"),
                    }
                )
            return result

        if action == "issue_face_token":
            self._require_greeter_or_root(uid, peer_username)
            username = str(data.get("username", ""))
            if USERNAME_PATTERN.fullmatch(username) is None:
                raise ValueError("ชื่อผู้ใช้ไม่ถูกต้อง")
            if self.manager.database.get_user_by_username(username) is None:
                raise ValueError("ไม่พบบัญชีผู้ใช้")
            FACE_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(FACE_TOKEN_DIR, 0o700)
            token_path = FACE_TOKEN_DIR / username
            temporary = FACE_TOKEN_DIR / f".{username}.{secrets.token_hex(8)}"
            temporary.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, token_path)
            return True

        if action == "get_device_settings":
            user = self._current_app_user(uid, peer_username)
            settings = self.manager.database.get_device_settings(user.id)
            return {
                "user_id": settings.user_id,
                "microphone_enabled": settings.microphone_enabled,
                "camera_enabled": settings.camera_enabled,
                "tts_enabled": settings.tts_enabled,
            }

        if action == "update_device_setting":
            user = self._current_app_user(uid, peer_username)
            self.manager.database.update_device_setting(
                user.id,
                str(data.get("device", "")),
                bool(data.get("enabled")),
            )
            return True

        if action == "get_current_user":
            user = self._current_app_user(uid, peer_username)
            return _serialize_user(user)

        if action == "get_user":
            user = self._current_app_user(uid, peer_username)
            return _serialize_user(user)

        if action == "user_has_face_profiles":
            user = self._current_app_user(uid, peer_username)
            return self.manager.database.user_has_face_profiles(user.id)

        if action == "replace_face_profiles":
            user = self._current_app_user(uid, peer_username)
            embeddings = [
                np.frombuffer(base64.b64decode(value), dtype=np.float32).copy()
                for value in data.get("embeddings", [])
            ]
            self.manager.database.replace_face_profiles(user.id, embeddings)
            return True

        if action == "get_recovery_gmail_status":
            user = self._current_app_user(uid, peer_username)
            gmail, verified = self.manager.database.get_recovery_gmail_status(user.id)
            return {"gmail": gmail, "verified": verified}

        if action == "recovery_gmail_in_use":
            user = self._current_app_user(uid, peer_username)
            return self.manager.database.recovery_gmail_in_use(
                str(data.get("gmail", "")),
                user.id,
            )

        if action == "update_user":
            user = self._current_app_user(uid, peer_username)
            requested_username = str(data.get("username", "")).strip()
            if requested_username != user.username:
                raise ValueError("ชื่อผู้ใช้ Linux ไม่สามารถเปลี่ยนได้")
            updated = self.manager.database.update_user(
                user.id,
                user.username,
                str(data.get("nickname", "")),
                str(data.get("recovery_gmail", "")),
                bool(data.get("recovery_gmail_verified", False)),
            )
            return _serialize_user(updated)

        if action == "change_password":
            user = self._current_app_user(uid, peer_username)
            self.manager.change_password(
                user.id,
                str(data.get("current", "")),
                str(data.get("new", "")),
            )
            return True

        if action == "reset_password":
            user = self._current_app_user(uid, peer_username)
            self.manager.reset_password(user.id, str(data.get("new", "")))
            return True

        if action == "power":
            self._require_greeter_or_root(uid, peer_username)
            operation = str(data.get("operation", ""))
            if operation not in {"reboot", "poweroff"}:
                raise ValueError("คำสั่งจัดการพลังงานไม่ถูกต้อง")
            self.manager.power(operation)
            return True

        raise ValueError("ไม่รู้จักคำสั่งที่ร้องขอ")


def main() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    FACE_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUNTIME_DIR, 0o755)
    with AuthServer() as server:
        server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
