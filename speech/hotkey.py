import threading
from collections.abc import Callable


class PushToTalkHotkey:
    """Expose press/release state for one global push-to-talk key."""

    def __init__(
        self,
        on_talk_pressed: Callable[[], None] | None = None,
        on_talk_released: Callable[[], None] | None = None,
        on_stop_pressed: Callable[[], None] | None = None,
    ) -> None:
        self._condition = threading.Condition()
        self._pressed = False
        self._stop_pressed = False
        self._closed = False
        self._listener = None
        self._talk_key = None
        self._stop_key = None
        self._reported_values: set[str] = set()
        self._on_talk_pressed = on_talk_pressed
        self._on_talk_released = on_talk_released
        self._on_stop_pressed = on_stop_pressed

    def start(self) -> None:
        if self._listener is not None:
            return
        with self._condition:
            self._closed = False
        try:
            from pynput import keyboard
        except (ImportError, OSError) as error:
            raise RuntimeError(
                "เริ่มระบบปุ่ม F9 ไม่สำเร็จ กรุณาตรวจสอบ pynput และระบบหน้าจอ"
            ) from error

        self._talk_key = keyboard.Key.f9
        self._stop_key = keyboard.Key.f10
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        self._listener.wait()
        if not self._listener.is_alive():
            self.close()
            raise RuntimeError("เริ่มตรวจจับปุ่ม F9 ไม่สำเร็จ")

    def close(self) -> None:
        listener = self._listener
        self._listener = None
        with self._condition:
            self._closed = True
            self._pressed = False
            self._stop_pressed = False
            self._condition.notify_all()
        if listener is not None:
            listener.stop()

    def _on_press(self, key) -> None:
        if key == self._stop_key:
            callback = None
            with self._condition:
                if self._stop_pressed:
                    return
                self._stop_pressed = True
                self._report_key(key)
                callback = self._on_stop_pressed
            self._invoke(callback)
            return
        if key != self._talk_key:
            return
        callback = None
        with self._condition:
            if self._pressed:
                return
            self._pressed = True
            self._report_key(key)
            callback = self._on_talk_pressed
            self._condition.notify_all()
        self._invoke(callback)

    def _on_release(self, key) -> None:
        if key == self._stop_key:
            with self._condition:
                self._stop_pressed = False
            return
        if key != self._talk_key:
            return
        callback = None
        with self._condition:
            self._pressed = False
            callback = self._on_talk_released
            self._condition.notify_all()
        self._invoke(callback)

    def _report_key(self, key) -> None:
        value = str(key)
        if value in self._reported_values:
            return
        print(f"\nค่าปุ่มที่ตรวจพบ: {value}")
        self._reported_values.add(value)

    @staticmethod
    def _invoke(callback: Callable[[], None] | None) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as error:
            print(f"HOTKEY ERROR: {error}")
