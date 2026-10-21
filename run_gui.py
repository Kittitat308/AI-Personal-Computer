import asyncio
from pathlib import Path

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from app.application import DesktopApplication


def main() -> None:
    qt_app = QApplication([])
    qt_app.setApplicationName("AI Personal Computer")
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    desktop = DesktopApplication(Path(__file__).resolve().parent)
    qt_app.aboutToQuit.connect(loop.stop)

    with loop:
        loop.run_until_complete(desktop.start())
        loop.run_forever()
        loop.run_until_complete(desktop.close())


if __name__ == "__main__":
    main()
