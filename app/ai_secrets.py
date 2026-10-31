from pathlib import Path

from app.database import Database


def migrate_legacy_api_keys(database: Database, project_root: Path) -> None:
    """Move keys saved as secrets/users/<id>/gemini_api_key.txt into the database."""
    root = project_root / "secrets" / "users"
    if not root.is_dir():
        return
    for path in root.glob("*/gemini_api_key.txt"):
        try:
            user_id = int(path.parent.name)
            api_key = path.read_text(encoding="utf-8").strip()
        except (ValueError, OSError):
            continue
        if database.get_user(user_id) is None:
            continue
        if api_key and not database.get_api_key(user_id, "gemini"):
            database.set_api_key(user_id, "gemini", api_key)
        if database.get_api_key(user_id, "gemini") == api_key or not api_key:
            path.unlink(missing_ok=True)
