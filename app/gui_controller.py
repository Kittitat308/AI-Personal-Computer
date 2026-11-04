from pathlib import Path

from core.controller import Controller


class GUIController(Controller):
    def set_temporary_attachment_directory(self, path: Path | None) -> None:
        self.worker.set_temporary_attachment_directory(path)

    async def set_active_user(self, user_id: int | None) -> None:
        await self.registry.set_active_user(user_id)
