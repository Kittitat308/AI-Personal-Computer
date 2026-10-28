import asyncio
import os
import signal
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from app.application import DesktopApplication


def main() -> None:
    qt_app = QApplication([])
    qt_app.setApplicationName("AI Personal Computer")
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    desktop = DesktopApplication(Path(__file__).resolve().parent)
    if os.environ.get("AIPC_SYSTEM_MODE") == "1":
        def show_window(_signal_number, _frame) -> None:
            QTimer.singleShot(0, desktop.window.showMaximized)

        def stop_service(_signal_number, _frame) -> None:
            QTimer.singleShot(0, qt_app.quit)

        signal.signal(signal.SIGUSR1, show_window)
        signal.signal(signal.SIGTERM, stop_service)
    qt_app.aboutToQuit.connect(loop.stop)

    with loop:
        loop.run_until_complete(desktop.start())
        loop.run_forever()
        loop.run_until_complete(desktop.close())


if __name__ == "__main__":
    main()
