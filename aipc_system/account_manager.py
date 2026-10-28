import json
import pwd
import socket
from pathlib import Path

import numpy as np

from app.database import Database, User
from aipc_system.paths import ACCOUNT_HELPER_SOCKET, AUTH_DATABASE


class AccountManager:
    """Own the transaction between the application account and Linux account."""

    def __init__(self, database_path: Path = AUTH_DATABASE):
        self.database = Database(database_path)

    @staticmethod
    def linux_user_exists(username: str) -> bool:
        try:
            pwd.getpwnam(username)
        except KeyError:
            return False
        return True

    @staticmethod
    def _helper(operation: str, **data) -> dict:
        request = (json.dumps(
            {"operation": operation, "data": data},
            ensure_ascii=False,
        ) + "\n").encode("utf-8")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(30)
                connection.connect(str(ACCOUNT_HELPER_SOCKET))
                connection.sendall(request)
                response_file = connection.makefile("rb")
                raw = response_file.readline(65537)
        except OSError as error:
            raise RuntimeError("ตัวช่วยจัดการบัญชียังไม่พร้อม") from error
        if not raw or len(raw) > 65536:
            raise RuntimeError("ตัวช่วยจัดการบัญชีตอบกลับไม่ถูกต้อง")
        response = json.loads(raw.decode("utf-8"))
        if not response.get("ok"):
            reason = str(response.get("error") or "จัดการบัญชีไม่สำเร็จ")
            if "BAD PASSWORD" in reason.upper() or "เดาง่าย" in reason:
                raise ValueError("รหัสผ่านเดาง่ายเกินไป")
            raise ValueError(reason)
        return response

    def create_user(
        self,
        username: str,
        nickname: str,
        password: str,
        embeddings: list[np.ndarray] | None = None,
        recovery_gmail: str = "",
        recovery_gmail_verified: bool = False,
    ) -> User:
        errors = self.database.validate_new_user(
            username,
            nickname,
            password,
            recovery_gmail,
        )
        if errors:
            raise ValueError(next(iter(errors.values())))
        if self.linux_user_exists(username):
            raise ValueError("ชื่อผู้ใช้นี้มีอยู่ในระบบแล้ว")

        self._helper(
            "create",
            username=username,
            nickname=nickname,
            password=password,
        )
        try:
            return self.database.create_user(
                username,
                nickname,
                password,
                embeddings or [],
                recovery_gmail,
                recovery_gmail_verified,
            )
        except Exception:
            self._helper("rollback-create", username=username)
            raise

    def change_password(self, user_id: int, current: str, new: str) -> None:
        user = self.database.get_user(user_id)
        if user is None:
            raise ValueError("ไม่พบบัญชีผู้ใช้")
        if self.database.authenticate(user.username, current) is None:
            raise ValueError("รหัสผ่านปัจจุบันไม่ถูกต้อง")
        self.database._validate_password(new, "รหัสผ่านใหม่")
        self._helper("set-password", username=user.username, password=new)
        self.database.change_password(user_id, current, new)

    def reset_password(self, user_id: int, new: str) -> None:
        user = self.database.get_user(user_id)
        if user is None:
            raise ValueError("ไม่พบบัญชีผู้ใช้")
        self.database._validate_password(new, "รหัสผ่านใหม่")
        self._helper("set-password", username=user.username, password=new)
        self.database.reset_password(user_id, new)

    def power(self, operation: str) -> None:
        if operation not in {"reboot", "poweroff"}:
            raise ValueError("คำสั่งจัดการพลังงานไม่ถูกต้อง")
        self._helper(operation)
