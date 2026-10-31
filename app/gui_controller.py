from pathlib import Path

from core.controller import Controller
from providers.catalog import DEFAULT_EFFORT


class GUIController(Controller):
    def __init__(self):
        super().__init__()
        self._allowed_directory: str | None = None

    def set_allowed_directory(self, path: str | None) -> None:
        self._allowed_directory = path
        self.worker.set_allowed_directory(path)

    def set_temporary_attachment_directory(self, path: Path | None) -> None:
        self.worker.set_temporary_attachment_directory(path)

    async def configure_provider(
        self,
        name: str,
        model: str,
        effort: str = DEFAULT_EFFORT,
        api_key: str = "",
    ) -> None:
        await super().configure_provider(name, model, effort, api_key)
        self.worker.set_allowed_directory(self._allowed_directory)

    async def set_active_user(self, user_id: int | None) -> None:
        await self.registry.set_active_user(user_id)
