import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


@dataclass(frozen=True)
class User:
    id: int
    username: str
    nickname: str


@dataclass(frozen=True)
class DeviceSettings:
    user_id: int
    microphone_enabled: bool
    camera_enabled: bool
    tts_enabled: bool


USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,31}$")
USERNAME_START_PATTERN = re.compile(r"^[a-z]")
NICKNAME_PATTERN = re.compile(
    r"^(?:[A-Za-z]+(?: [A-Za-z]+)*|"
    r"[\u0E01-\u0E2E\u0E30-\u0E3A\u0E40-\u0E4E]+"
    r"(?: [\u0E01-\u0E2E\u0E30-\u0E3A\u0E40-\u0E4E]+)*)$"
)
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9]{8,}$")
GMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@gmail\.com$", re.IGNORECASE)
DEVICE_SETTING_COLUMNS = {
    "microphone": "microphone_enabled",
    "camera": "camera_enabled",
    "tts": "tts_enabled",
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._hasher = PasswordHasher()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE
                        CHECK (
                            length(username) BETWEEN 1 AND 32
                            AND username GLOB '[a-z]*'
                            AND username NOT GLOB '*[^a-z0-9]*'
                        ),
                    nickname TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    recovery_gmail TEXT,
                    recovery_gmail_verified INTEGER NOT NULL DEFAULT 0
                        CHECK (recovery_gmail_verified IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS face_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_face_profiles_user_id
                    ON face_profiles(user_id);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "nickname" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN nickname TEXT NOT NULL DEFAULT ''"
                )
            if "recovery_gmail" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN recovery_gmail TEXT")
            if "recovery_gmail_verified" not in columns:
                connection.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN recovery_gmail_verified INTEGER NOT NULL DEFAULT 0
                        CHECK (recovery_gmail_verified IN (0, 1))
                    """
                )
            connection.execute(
                "UPDATE users SET nickname = username WHERE TRIM(nickname) = ''"
            )
            self._enforce_linux_username_rules(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS device_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    microphone_enabled INTEGER NOT NULL DEFAULT 1 CHECK (microphone_enabled IN (0, 1)),
                    camera_enabled INTEGER NOT NULL DEFAULT 1 CHECK (camera_enabled IN (0, 1)),
                    tts_enabled INTEGER NOT NULL DEFAULT 1 CHECK (tts_enabled IN (0, 1)),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                INSERT OR IGNORE INTO device_settings(user_id)
                SELECT id FROM users;
                """
            )

    @staticmethod
    def _enforce_linux_username_rules(connection: sqlite3.Connection) -> None:
        duplicate = connection.execute(
            """
            SELECT lower(username) AS normalized
            FROM users
            GROUP BY lower(username)
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate is not None:
            raise RuntimeError(
                "มีชื่อผู้ใช้ซ้ำกันเมื่อไม่แยกตัวพิมพ์เล็กและใหญ่ "
                "กรุณาแก้ชื่อผู้ใช้ก่อนเปิดระบบ"
            )

        invalid = connection.execute(
            """
            SELECT username
            FROM users
            WHERE length(username) NOT BETWEEN 1 AND 32
               OR lower(username) NOT GLOB '[a-z]*'
               OR lower(username) GLOB '*[^a-z0-9]*'
            LIMIT 1
            """
        ).fetchone()
        if invalid is not None:
            raise RuntimeError(
                "ชื่อผู้ใช้เดิมไม่ตรงกับกฎของ Linux account: "
                f"{invalid['username']}"
            )

        connection.execute(
            "UPDATE users SET username = lower(username) WHERE username <> lower(username)"
        )
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase
                ON users(username COLLATE NOCASE);

            CREATE TRIGGER IF NOT EXISTS validate_users_username_insert
            BEFORE INSERT ON users
            WHEN length(NEW.username) NOT BETWEEN 1 AND 32
              OR NEW.username NOT GLOB '[a-z]*'
              OR NEW.username GLOB '*[^a-z0-9]*'
            BEGIN
                SELECT RAISE(ABORT, 'invalid Linux username');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_users_username_update
            BEFORE UPDATE OF username ON users
            WHEN length(NEW.username) NOT BETWEEN 1 AND 32
              OR NEW.username NOT GLOB '[a-z]*'
              OR NEW.username GLOB '*[^a-z0-9]*'
            BEGIN
                SELECT RAISE(ABORT, 'invalid Linux username');
            END;
            """
        )

    def create_user(
        self,
        username: str,
        nickname: str,
        password: str,
        embeddings: list[np.ndarray] | None = None,
        recovery_gmail: str = "",
        recovery_gmail_verified: bool = False,
    ) -> User:
        username = username.strip()
        nickname = nickname.strip()
        recovery_gmail = recovery_gmail.strip()
        validation_errors = self.validate_new_user(
            username,
            nickname,
            password,
            recovery_gmail,
        )
        if validation_errors:
            raise ValueError(next(iter(validation_errors.values())))

        password_hash = self._hasher.hash(password)
        with self._lock, self._connection() as connection:
            if recovery_gmail and self._recovery_gmail_owner(
                connection,
                recovery_gmail,
            ) is not None:
                raise ValueError("Gmail นี้ถูกใช้งานไปแล้ว")
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO users(
                        username, nickname, password_hash, recovery_gmail,
                        recovery_gmail_verified
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        nickname,
                        password_hash,
                        recovery_gmail or None,
                        int(bool(recovery_gmail and recovery_gmail_verified)),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("ชื่อผู้ใช้นี้มีอยู่แล้ว") from error

            user_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO device_settings(user_id) VALUES (?)",
                (user_id,),
            )
            self._replace_embeddings(connection, user_id, embeddings or [])
            return User(user_id, username, nickname)

    def get_device_settings(self, user_id: int) -> DeviceSettings:
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO device_settings(user_id) VALUES (?)",
                (user_id,),
            )
            row = connection.execute(
                """
                SELECT user_id, microphone_enabled, camera_enabled, tts_enabled
                FROM device_settings
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise ValueError("ไม่พบการตั้งค่าอุปกรณ์ของผู้ใช้")
        return DeviceSettings(
            user_id=int(row["user_id"]),
            microphone_enabled=bool(row["microphone_enabled"]),
            camera_enabled=bool(row["camera_enabled"]),
            tts_enabled=bool(row["tts_enabled"]),
        )

    def update_device_setting(self, user_id: int, device: str, enabled: bool) -> None:
        column = DEVICE_SETTING_COLUMNS.get(device)
        if column is None:
            raise ValueError("ชื่ออุปกรณ์ไม่ถูกต้อง")
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO device_settings(user_id) VALUES (?)",
                (user_id,),
            )
            connection.execute(
                f"UPDATE device_settings SET {column} = ? WHERE user_id = ?",
                (int(enabled), user_id),
            )

    def authenticate(self, username: str, password: str) -> User | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT id, username, nickname, password_hash FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        if row is None:
            return None
        try:
            self._hasher.verify(row["password_hash"], password)
        except VerifyMismatchError:
            return None
        if self._hasher.check_needs_rehash(row["password_hash"]):
            with self._lock, self._connection() as connection:
                connection.execute(
                    "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (self._hasher.hash(password), row["id"]),
                )
        return User(int(row["id"]), str(row["username"]), str(row["nickname"]))

    def list_face_profiles(self) -> list[tuple[User, np.ndarray]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT users.id, users.username, users.nickname, face_profiles.embedding
                FROM face_profiles
                JOIN users ON users.id = face_profiles.user_id
                ORDER BY users.id, face_profiles.id
                """
            ).fetchall()
        return [
            (
                User(
                    int(row["id"]),
                    str(row["username"]),
                    str(row["nickname"]),
                ),
                np.frombuffer(row["embedding"], dtype=np.float32).copy(),
            )
            for row in rows
        ]

    def replace_face_profiles(self, user_id: int, embeddings: list[np.ndarray]) -> None:
        if not embeddings:
            raise ValueError("ไม่พบข้อมูลใบหน้าสำหรับบันทึก")
        with self._lock, self._connection() as connection:
            self._replace_embeddings(connection, user_id, embeddings)

    def user_has_face_profiles(self, user_id: int) -> bool:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM face_profiles WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
        return row is not None

    def get_user(self, user_id: int) -> User | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT id, username, nickname FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return User(int(row["id"]), str(row["username"]), str(row["nickname"]))

    def get_verified_recovery_gmail(self, user_id: int) -> str:
        gmail, verified = self.get_recovery_gmail_status(user_id)
        return gmail if verified else ""

    def get_user_by_verified_recovery_gmail(
        self,
        recovery_gmail: str,
    ) -> User | None:
        recovery_gmail = recovery_gmail.strip()
        if not recovery_gmail:
            return None
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, username, nickname
                FROM users
                WHERE recovery_gmail = ? COLLATE NOCASE
                  AND recovery_gmail_verified = 1
                LIMIT 1
                """,
                (recovery_gmail,),
            ).fetchone()
        if row is None:
            return None
        return User(int(row["id"]), str(row["username"]), str(row["nickname"]))

    def get_recovery_gmail_status(self, user_id: int) -> tuple[str, bool]:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT recovery_gmail, recovery_gmail_verified
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None or row["recovery_gmail"] is None:
            return "", False
        return (
            str(row["recovery_gmail"]).strip(),
            bool(row["recovery_gmail_verified"]),
        )

    def recovery_gmail_in_use(
        self,
        recovery_gmail: str,
        exclude_user_id: int | None = None,
    ) -> bool:
        recovery_gmail = recovery_gmail.strip()
        if not recovery_gmail:
            return False
        with self._lock, self._connection() as connection:
            return self._recovery_gmail_owner(
                connection,
                recovery_gmail,
                exclude_user_id,
            ) is not None

    @staticmethod
    def _recovery_gmail_owner(
        connection: sqlite3.Connection,
        recovery_gmail: str,
        exclude_user_id: int | None = None,
    ) -> int | None:
        query = (
            "SELECT id FROM users "
            "WHERE recovery_gmail = ? COLLATE NOCASE"
        )
        parameters: list[object] = [recovery_gmail.strip()]
        if exclude_user_id is not None:
            query += " AND id <> ?"
            parameters.append(exclude_user_id)
        query += " LIMIT 1"
        row = connection.execute(query, parameters).fetchone()
        return None if row is None else int(row["id"])

    @staticmethod
    def _replace_embeddings(
        connection: sqlite3.Connection,
        user_id: int,
        embeddings: list[np.ndarray],
    ) -> None:
        if not embeddings:
            return
        connection.execute("DELETE FROM face_profiles WHERE user_id = ?", (user_id,))
        connection.executemany(
            "INSERT INTO face_profiles(user_id, embedding) VALUES (?, ?)",
            [
                (user_id, np.asarray(item, dtype=np.float32).tobytes())
                for item in embeddings
            ],
        )

    def update_user(
        self,
        user_id: int,
        username: str,
        nickname: str,
        recovery_gmail: str = "",
        recovery_gmail_verified: bool = False,
    ) -> User:
        username = username.strip()
        nickname = nickname.strip()
        recovery_gmail = recovery_gmail.strip()
        errors = self.validate_user_profile(username, nickname, recovery_gmail)
        if errors:
            raise ValueError(next(iter(errors.values())))
        with self._lock, self._connection() as connection:
            if recovery_gmail and self._recovery_gmail_owner(
                connection,
                recovery_gmail,
                user_id,
            ) is not None:
                raise ValueError("Gmail นี้ถูกใช้งานไปแล้ว")
            try:
                connection.execute(
                    """
                    UPDATE users
                    SET username = ?, nickname = ?, recovery_gmail = ?,
                        recovery_gmail_verified = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        username,
                        nickname,
                        recovery_gmail or None,
                        int(bool(recovery_gmail and recovery_gmail_verified)),
                        user_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("ชื่อผู้ใช้นี้มีอยู่แล้ว") from error
        return User(user_id, username, nickname)

    @staticmethod
    def validate_user_profile(
        username: str,
        nickname: str,
        recovery_gmail: str = "",
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        username = username.strip()
        nickname = nickname.strip()
        recovery_gmail = recovery_gmail.strip()
        if not username:
            errors["username"] = "กรุณากรอกชื่อผู้ใช้"
        elif USERNAME_START_PATTERN.match(username) is None:
            errors["username"] = (
                "ชื่อผู้ใช้ต้องขึ้นต้นด้วยตัวอักษรภาษาอังกฤษตัวเล็ก"
            )
        elif len(username) > 32:
            errors["username"] = "ชื่อผู้ใช้ต้องไม่เกิน 32 ตัวอักษร"
        elif USERNAME_PATTERN.fullmatch(username) is None:
            errors["username"] = (
                "ใช้ได้เฉพาะตัวอักษรภาษาอังกฤษตัวเล็กกับตัวเลขเท่านั้น"
            )
        if not nickname:
            errors["nickname"] = "กรุณากรอกชื่อเล่น"
        elif NICKNAME_PATTERN.fullmatch(nickname) is None:
            errors["nickname"] = (
                "ชื่อเล่นต้องเป็นภาษาไทยล้วนหรืออังกฤษล้วน"
            )
        recovery_error = Database.validate_recovery_gmail(recovery_gmail)
        if recovery_error:
            errors["recovery_gmail"] = recovery_error
        return errors

    @staticmethod
    def validate_recovery_gmail(recovery_gmail: str) -> str:
        recovery_gmail = recovery_gmail.strip()
        if recovery_gmail and GMAIL_PATTERN.fullmatch(recovery_gmail) is None:
            return "รูปแบบ Gmail ไม่ถูกต้อง"
        return ""

    @staticmethod
    def validate_new_user(
        username: str,
        nickname: str,
        password: str,
        recovery_gmail: str = "",
    ) -> dict[str, str]:
        errors = Database.validate_user_profile(
            username,
            nickname,
            recovery_gmail,
        )
        if PASSWORD_PATTERN.fullmatch(password) is None:
            errors["password"] = (
                "รหัสผ่านต้องมีอังกฤษและตัวเลข อย่างน้อย 8 ตัว"
            )
        return errors

    def change_password(self, user_id: int, current: str, new: str) -> None:
        self._validate_password(new, "รหัสผ่านใหม่")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                raise ValueError("ไม่พบบัญชีผู้ใช้")
            try:
                self._hasher.verify(row["password_hash"], current)
            except VerifyMismatchError as error:
                raise ValueError("รหัสผ่านปัจจุบันไม่ถูกต้อง") from error
            connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (self._hasher.hash(new), user_id),
            )

    def reset_password(self, user_id: int, new: str) -> None:
        self._validate_password(new, "รหัสผ่านใหม่")
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (self._hasher.hash(new), user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("ไม่พบบัญชีผู้ใช้")

    @staticmethod
    def _validate_password(password: str, label: str = "รหัสผ่าน") -> None:
        if PASSWORD_PATTERN.fullmatch(password) is None:
            raise ValueError(
                f"{label}ต้องมีอังกฤษและตัวเลข อย่างน้อย 8 ตัว"
            )
