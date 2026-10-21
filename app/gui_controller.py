from pathlib import Path

from core.controller import Controller
from core.worker import WorkerAI


class GUIWorkerAI(WorkerAI):
    """Worker variant that grants one user-selected folder per new task."""

    def __init__(self, registry):
        super().__init__(registry)
        self.allowed_directory: Path | None = None

    def set_allowed_directory(self, path: str | None) -> None:
        self.allowed_directory = Path(path).resolve() if path else None

    def _create_session(self, definitions, mcp_servers):
        session = super()._create_session(definitions, mcp_servers)
        if self.allowed_directory is not None:
            session.arguments.extend(["--add-dir", str(self.allowed_directory)])
        return session


class GUIController(Controller):
    def __init__(self):
        super().__init__()
        self.worker = GUIWorkerAI(self.registry)

    def set_allowed_directory(self, path: str | None) -> None:
        self.worker.set_allowed_directory(path)
