import base64
import json
import socket
from pathlib import Path

import numpy as np

from app.database import Database, DeviceSettings, User
from aipc_system.paths import AUTH_SOCKET


class AuthClient:
    def __init__(self, socket_path: Path = AUTH_SOCKET):
        self.socket_path = socket_path

    def _request(self, action: str, **data):
        payload = json.dumps(
            {"action": action, "data": data},
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(20)
            connection.connect(str(self.socket_path))
            connection.sendall(payload)
            response_file = connection.makefile("rb")
            response = json.loads(response_file.readline(1024 * 1024).decode("utf-8"))
        if not response.get("ok"):
            raise ValueError(str(response.get("error") or "บริการบัญชีล้มเหลว"))
        return response.get("result")

    @staticmethod
    def _user(data) -> User | None:
        if not data:
            return None
        return User(int(data["id"]), str(data["username"]), str(data["nickname"]))

    def health(self) -> bool:
        return self._request("health").get("status") == "ok"

    def authenticate(self, username: str, password: str) -> User | None:
        return self._user(
            self._request("authenticate", username=username, password=password)
        )

    def get_user_by_verified_recovery_gmail(self, gmail: str) -> User | None:
        return self._user(
            self._request("get_user_by_verified_recovery_gmail", gmail=gmail)
        )

    def recovery_gmail_in_use_public(self, gmail: str) -> bool:
        return bool(self._request("recovery_gmail_in_use_public", gmail=gmail))

    def reset_password_for_user(self, user_id: int, new: str) -> None:
        self._request("reset_password_for_user", user_id=user_id, new=new)

    def create_user(
        self,
        username: str,
        nickname: str,
        password: str,
        embeddings: list[np.ndarray] | None = None,
        recovery_gmail: str = "",
        recovery_gmail_verified: bool = False,
    ) -> User:
        encoded = [
            base64.b64encode(np.asarray(item, dtype=np.float32).tobytes()).decode("ascii")
            for item in (embeddings or [])
        ]
        return self._user(
            self._request(
                "create_user",
                username=username,
                nickname=nickname,
                password=password,
                embeddings=encoded,
                recovery_gmail=recovery_gmail,
                recovery_gmail_verified=recovery_gmail_verified,
            )
        )

    def list_face_profiles(self) -> list[tuple[User, np.ndarray]]:
        result = []
        for item in self._request("list_face_profiles"):
            result.append(
                (
                    self._user(item["user"]),
                    np.frombuffer(
                        base64.b64decode(item["embedding"]),
                        dtype=np.float32,
                    ).copy(),
                )
            )
        return result

    def issue_face_token(self, username: str) -> None:
        self._request("issue_face_token", username=username)

    def get_device_settings(self, _user_id: int | None = None) -> DeviceSettings:
        data = self._request("get_device_settings")
        return DeviceSettings(
            int(data["user_id"]),
            bool(data["microphone_enabled"]),
            bool(data["camera_enabled"]),
            bool(data["tts_enabled"]),
        )

    def update_device_setting(
        self,
        _user_id: int | None,
        device: str,
        enabled: bool,
    ) -> None:
        self._request(
            "update_device_setting",
            device=device,
            enabled=enabled,
        )

    def get_current_user(self) -> User:
        return self._user(self._request("get_current_user"))

    def get_user(self, _user_id: int | None = None) -> User:
        return self._user(self._request("get_user"))

    def user_has_face_profiles(self, _user_id: int | None = None) -> bool:
        return bool(self._request("user_has_face_profiles"))

    def replace_face_profiles(
        self,
        _user_id: int | None,
        embeddings: list[np.ndarray],
    ) -> None:
        encoded = [
            base64.b64encode(np.asarray(item, dtype=np.float32).tobytes()).decode("ascii")
            for item in embeddings
        ]
        self._request("replace_face_profiles", embeddings=encoded)

    def get_recovery_gmail_status(
        self,
        _user_id: int | None = None,
    ) -> tuple[str, bool]:
        data = self._request("get_recovery_gmail_status")
        return str(data["gmail"]), bool(data["verified"])

    def get_recovery_gmail(self, user_id: int | None = None) -> str:
        return self.get_recovery_gmail_status(user_id)[0]

    def get_verified_recovery_gmail(self, user_id: int | None = None) -> str:
        gmail, verified = self.get_recovery_gmail_status(user_id)
        return gmail if verified else ""

    def recovery_gmail_in_use(
        self,
        gmail: str,
        _exclude_user_id: int | None = None,
    ) -> bool:
        return bool(self._request("recovery_gmail_in_use", gmail=gmail))

    def update_user(
        self,
        _user_id: int | None,
        username: str,
        nickname: str,
        recovery_gmail: str = "",
        recovery_gmail_verified: bool = False,
    ) -> User:
        return self._user(
            self._request(
                "update_user",
                username=username,
                nickname=nickname,
                recovery_gmail=recovery_gmail,
                recovery_gmail_verified=recovery_gmail_verified,
            )
        )

    def change_password(
        self,
        _user_id: int | None,
        current: str,
        new: str,
    ) -> None:
        self._request("change_password", current=current, new=new)

    def reset_password(self, _user_id: int | None, new: str) -> None:
        self._request("reset_password", new=new)

    validate_user_profile = staticmethod(Database.validate_user_profile)
    validate_new_user = staticmethod(Database.validate_new_user)
    validate_recovery_gmail = staticmethod(Database.validate_recovery_gmail)

    def power(self, operation: str) -> None:
        self._request("power", operation=operation)
