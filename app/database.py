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


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


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
                    username TEXT NOT NULL UNIQUE COLLATE BINARY,
                    nickname TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
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
            connection.execute(
                "UPDATE users SET nickname = username WHERE TRIM(nickname) = ''"
            )
            self._migrate_username_to_case_sensitive(connection)

    @staticmethod
    def _migrate_username_to_case_sensitive(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()
        schema = "" if row is None else str(row["sql"] or "")
        if "COLLATE NOCASE" not in schema.upper():
            return

        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;

                ALTER TABLE face_profiles RENAME TO face_profiles_case_backup;
                ALTER TABLE users RENAME TO users_case_backup;

                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE BINARY,
                    nickname TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO users(
                    id, username, nickname, password_hash, created_at, updated_at
                )
                SELECT
                    id, username, nickname, password_hash, created_at, updated_at
                FROM users_case_backup;

                CREATE TABLE face_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                INSERT INTO face_profiles(id, user_id, embedding, created_at)
                SELECT id, user_id, embedding, created_at
                FROM face_profiles_case_backup;

                DROP TABLE face_profiles_case_backup;
                DROP TABLE users_case_backup;

                CREATE INDEX idx_face_profiles_user_id
                    ON face_profiles(user_id);

                COMMIT;
                """
            )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError("การย้ายฐานข้อมูลผู้ใช้ทำให้ความสัมพันธ์ข้อมูลไม่ถูกต้อง")

    def create_user(
        self,
        username: str,
        nickname: str,
        password: str,
        embeddings: list[np.ndarray] | None = None,
    ) -> User:
        username = username.strip()
        nickname = nickname.strip()
        self._validate_username(username)
        if not nickname:
            raise ValueError("กรุณากรอกชื่อเล่น")
        if len(password) < 8:
            raise ValueError("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")

        password_hash = self._hasher.hash(password)
        with self._lock, self._connection() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO users(username, nickname, password_hash) VALUES (?, ?, ?)",
                    (username, nickname, password_hash),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("ชื่อผู้ใช้นี้มีอยู่แล้ว") from error

            user_id = int(cursor.lastrowid)
            self._replace_embeddings(connection, user_id, embeddings or [])
            return User(user_id, username, nickname)

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

    def has_face_profiles(self) -> bool:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM face_profiles LIMIT 1"
            ).fetchone()
        return row is not None

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

    def update_user(self, user_id: int, username: str, nickname: str) -> User:
        username = username.strip()
        nickname = nickname.strip()
        self._validate_username(username)
        if not nickname:
            raise ValueError("กรุณากรอกชื่อเล่น")
        with self._lock, self._connection() as connection:
            try:
                connection.execute(
                    """
                    UPDATE users
                    SET username = ?, nickname = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (username, nickname, user_id),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("ชื่อผู้ใช้นี้มีอยู่แล้ว") from error
        return User(user_id, username, nickname)

    @staticmethod
    def _validate_username(username: str) -> None:
        if not username:
            raise ValueError("กรุณากรอกชื่อผู้ใช้")
        if USERNAME_PATTERN.fullmatch(username) is None:
            raise ValueError(
                "ชื่อผู้ใช้ใช้ได้เฉพาะตัวอักษรภาษาอังกฤษและตัวเลขเท่านั้น"
            )

    def change_password(self, user_id: int, current: str, new: str) -> None:
        if len(new) < 8:
            raise ValueError("รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร")
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
        if len(new) < 8:
            raise ValueError("รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร")
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
