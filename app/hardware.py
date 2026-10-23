import cv2
import sounddevice as sd


class HardwareManager:
    MICROPHONE_SAMPLE_RATE = 16_000

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
            devices = sd.query_devices()
            default_input = sd.default.device[0]
            candidates = []
            if isinstance(default_input, int) and default_input >= 0:
                candidates.append(default_input)
            candidates.extend(
                index
                for index, device in enumerate(devices)
                if index not in candidates
                and int(device.get("max_input_channels", 0)) > 0
            )
            for index in candidates:
                device = devices[index]
                if int(device.get("max_input_channels", 0)) <= 0:
                    continue
                try:
                    sd.check_input_settings(
                        device=index,
                        channels=1,
                        dtype="float32",
                        samplerate=HardwareManager.MICROPHONE_SAMPLE_RATE,
                    )
                except Exception:
                    continue
                output_device = sd.default.device[1]
                sd.default.device = (index, output_device)
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def speaker_available() -> bool:
        try:
            device = sd.query_devices(kind="output")
            return int(device.get("max_output_channels", 0)) > 0
        except Exception:
            return False
