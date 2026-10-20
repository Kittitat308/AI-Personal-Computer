import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from speech.stt.config import (
    CANCEL_REQUEST_TIMEOUT_SECONDS,
    CANCEL_WAIT_TIMEOUT_SECONDS,
    CHANNELS,
    HOST,
    INFERENCE_TIMEOUT_SECONDS,
    LANGUAGE,
    MODEL_PATH,
    PORT,
    SAMPLE_RATE,
    SERVER_START_TIMEOUT_SECONDS,
    STT_RETRY_AUDIO_PATH,
    THREADS,
    WARMUP_AUDIO_PATH,
    WARMUP_TIMEOUT_SECONDS,
    WHISPER_DIR,
    WHISPER_EXECUTABLE,
)


class STTService:
    def __init__(self) -> None:
        self.server_url = f"http://{HOST}:{PORT}"
        self.inference_url = f"{self.server_url}/inference"
        self.cancel_url = f"{self.server_url}/cancel"
        self.status_url = f"{self.server_url}/status"
        self.server_process: subprocess.Popen | None = None
        self.owns_server = False
        self.warmed_up = False

    def start(self) -> None:
        if self._server_is_ready():
            self._warm_up()
            return

        self._validate_files()
        print("กำลังโหลด Thonburian Whisper Distilled Small Q8 ด้วย CPU...")
        started = time.perf_counter()

        command = [
            str(WHISPER_EXECUTABLE),
            "--model",
            str(MODEL_PATH),
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--threads",
            str(THREADS),
            "--language",
            LANGUAGE,
            "--no-gpu",
            "--no-fallback",
            "--no-timestamps",
            "--suppress-nst",
            "--best-of",
            "1",
            "--max-context",
            "0",
        ]

        startup_flags = 0
        if os.name == "nt":
            startup_flags = subprocess.CREATE_NO_WINDOW

        self.server_process = subprocess.Popen(
            command,
            cwd=WHISPER_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=startup_flags,
        )
        self.owns_server = True

        deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self.server_process.poll() is not None:
                raise RuntimeError("Whisper Server ปิดตัวระหว่างโหลดโมเดล")

            if self._server_is_ready():
                load_elapsed = time.perf_counter() - started
                print(f"โหลดโมเดลสำเร็จ: {load_elapsed:.2f} วินาที")
                self._warm_up()
                return

            time.sleep(0.25)

        self.close()
        raise TimeoutError("รอ Whisper Server พร้อมใช้งานนานเกินไป")

    def listen(self) -> str:
        input("กด Enter เพื่อเปิดไมค์...")
        audio_path = self._record_audio()

        try:
            return self._transcribe(audio_path)
        finally:
            audio_path.unlink(missing_ok=True)

    def close(self) -> None:
        if not self.owns_server or self.server_process is None:
            return

        if self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()

        self.server_process = None
        self.owns_server = False
        self.warmed_up = False

    @staticmethod
    def is_shutdown_command(text: str) -> bool:
        normalized = re.sub(r"[\s.!?…。、，！？]+", "", text).casefold()
        return "ปิดระบบ" in normalized

    def _record_audio(self) -> Path:
        frames: list[np.ndarray] = []

        def callback(indata, _frames, _time_info, status) -> None:
            if status:
                print(f"MIC WARNING: {status}")
            frames.append(indata.copy())

        print("กำลังฟัง... พูดได้เลยครับ")
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=callback,
            ):
                input("กด Enter เพื่อหยุดไมค์...")
        except Exception as error:
            raise RuntimeError(f"เปิดไมโครโฟนไม่สำเร็จ: {error}") from error

        if not frames:
            raise RuntimeError("ไม่ได้รับข้อมูลเสียงจากไมโครโฟน")

        audio = np.concatenate(frames, axis=0)

        temporary = tempfile.NamedTemporaryFile(
            prefix="ai_pc_stt_",
            suffix=".wav",
            delete=False,
        )
        temporary.close()
        audio_path = Path(temporary.name)
        sf.write(audio_path, audio, SAMPLE_RATE, subtype="PCM_16")
        return audio_path

    def _transcribe(self, audio_path: Path) -> str:
        print("กำลังแปลงเสียงเป็นข้อความ...")
        started = time.perf_counter()

        try:
            with audio_path.open("rb") as audio_file:
                response = requests.post(
                    self.inference_url,
                    files={"file": ("input.wav", audio_file, "audio/wav")},
                    data={"language": LANGUAGE, "response_format": "json"},
                    timeout=INFERENCE_TIMEOUT_SECONDS,
                )
            response.raise_for_status()
        except requests.exceptions.Timeout as error:
            self._recover_from_timeout()
            raise TimeoutError(
                f"STT ใช้เวลาเกิน {INFERENCE_TIMEOUT_SECONDS:.0f} วินาทีและถูกยกเลิก"
            ) from error
        except requests.RequestException as error:
            self._recover_from_server_error()
            raise RuntimeError(f"Whisper Server ตอบกลับไม่สำเร็จ: {error}") from error

        try:
            text = str(response.json().get("text", "")).strip()
        except (ValueError, AttributeError):
            text = response.text.strip()

        elapsed = time.perf_counter() - started
        print(f"STT: {elapsed:.2f} วินาที")
        return text

    def _recover_from_timeout(self) -> None:
        sound_started = self._start_retry_sound()
        try:
            try:
                self._cancel_inference()
            except Exception as error:
                print(f"ยกเลิก STT ไม่สำเร็จ กำลังเริ่มเซิร์ฟเวอร์ใหม่: {error}")
                self._restart_server()
        finally:
            if sound_started:
                sd.wait()

    def _recover_from_server_error(self) -> None:
        sound_started = self._start_retry_sound()
        try:
            self._restart_server()
        finally:
            if sound_started:
                sd.wait()

    def _cancel_inference(self) -> None:
        response = requests.post(
            self.cancel_url,
            timeout=CANCEL_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        deadline = time.monotonic() + CANCEL_WAIT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            status_response = requests.get(
                self.status_url,
                timeout=CANCEL_REQUEST_TIMEOUT_SECONDS,
            )
            status_response.raise_for_status()
            if status_response.json().get("status") == "idle":
                return
            time.sleep(0.05)

        raise TimeoutError("Whisper Server ไม่กลับสู่สถานะ idle หลังยกเลิก")

    def _restart_server(self) -> None:
        self.close()
        self.start()

    @staticmethod
    def _start_retry_sound() -> bool:
        try:
            audio, sample_rate = sf.read(
                STT_RETRY_AUDIO_PATH,
                dtype="float32",
                always_2d=True,
            )
            sd.play(audio, sample_rate)
            return True
        except Exception as error:
            print(f"เล่นเสียงแจ้งเตือน STT ไม่สำเร็จ: {error}")
            return False

    def _warm_up(self) -> None:
        if self.warmed_up:
            return

        print("กำลัง warm-up STT...")
        started = time.perf_counter()
        with WARMUP_AUDIO_PATH.open("rb") as audio_file:
            response = requests.post(
                self.inference_url,
                files={"file": ("warmup.wav", audio_file, "audio/wav")},
                data={"language": LANGUAGE, "response_format": "json"},
                timeout=WARMUP_TIMEOUT_SECONDS,
            )
        response.raise_for_status()

        self.warmed_up = True
        elapsed = time.perf_counter() - started
        print(f"warm-up สำเร็จ: {elapsed:.2f} วินาที")
        print("STT พร้อมใช้งาน")

    def _server_is_ready(self) -> bool:
        try:
            requests.get(self.server_url, timeout=0.5)
            return True
        except requests.RequestException:
            return False

    @staticmethod
    def _validate_files() -> None:
        missing = [
            path
            for path in (
                WHISPER_EXECUTABLE,
                MODEL_PATH,
                WARMUP_AUDIO_PATH,
                STT_RETRY_AUDIO_PATH,
            )
            if not path.is_file()
        ]
        if missing:
            paths = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"ไม่พบไฟล์ STT: {paths}")
