import asyncio

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from aipc_system.greeter import GreeterApplication


def main() -> None:
    qt_app = QApplication([])
    qt_app.setApplicationName("AI Personal Computer Login")
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    greeter = GreeterApplication()
    qt_app.aboutToQuit.connect(loop.stop)
    with loop:
        loop.run_until_complete(greeter.start())
        loop.run_forever()
        loop.run_until_complete(greeter.close())


if __name__ == "__main__":
    main()
