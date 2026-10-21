import cv2
import sounddevice as sd


class HardwareManager:
    @staticmethod
    def camera_available() -> bool:
        capture = cv2.VideoCapture(0)
        try:
            return bool(capture.isOpened())
        finally:
            capture.release()

    @staticmethod
    def microphone_available() -> bool:
        try:
            device = sd.query_devices(kind="input")
            return int(device.get("max_input_channels", 0)) > 0
        except Exception:
            return False

    @staticmethod
    def speaker_available() -> bool:
        try:
            device = sd.query_devices(kind="output")
            return int(device.get("max_output_channels", 0)) > 0
        except Exception:
            return False
