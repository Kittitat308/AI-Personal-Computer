import asyncio
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.database import Database
from app.face import FaceService
from app.gui_controller import GUIController
from speech.hotkey import PushToTalkHotkey
from app.hardware import HardwareManager
from app.state import RuntimeState
from app.stt_adapter import GUISTTService
from app.ui import (
    FaceScanDialog,
    FormDialog,
    LoadingDialog,
    MainWindow,
    NoticeDialog,
    numpy_to_pixmap,
)
from app.voice import ManualRecorder, VoiceListener
from speech.wakeword import WakeWordListener, WakeWordService
from speech.tts import AudioQueue


class ThreadBridge(QObject):
    utterance = Signal(object)
    voice_error = Signal(str)
    push_to_talk_pressed = Signal()
    push_to_talk_released = Signal()
    stop_requested = Signal()


class DesktopApplication:
    ATTACHMENT_SUFFIXES = {".docx", ".pdf", ".pptx", ".xlsx"}
    INPUT_ATTACHMENT_SUFFIXES = ATTACHMENT_SUFFIXES | {
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
        ".txt", ".md", ".csv", ".json", ".py", ".html", ".xml",
    }
    MAX_INPUT_ATTACHMENT_SIZE = 25 * 1024 * 1024

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.state = RuntimeState()
        self.database = Database(project_root / "data" / "ai_personal_computer.db")
        self.attachment_cache = tempfile.TemporaryDirectory(prefix="ai_pc_attachments_")
        self.attachment_cache_path = Path(self.attachment_cache.name).resolve()
        self.input_attachment_cache: tempfile.TemporaryDirectory | None = None
        self.face = FaceService(self.database)
        self.controller = GUIController()
        self.stt = GUISTTService()
        self.audio_queue = AudioQueue()
        self.wakeword = WakeWordService()
        self.wakeword_listener: WakeWordListener | None = None
        self.wakeword_ready = False
        self.window = MainWindow()
        self.bridge = ThreadBridge()
        self.hotkeys = PushToTalkHotkey(
            on_talk_pressed=self.bridge.push_to_talk_pressed.emit,
            on_talk_released=self.bridge.push_to_talk_released.emit,
            on_stop_pressed=self.bridge.stop_requested.emit,
        )
        self.voice_listener: VoiceListener | None = None
        self.manual_recorder = ManualRecorder()
        self.push_to_talk_held = False
        self.push_to_talk_recording = False
        self.resume_voice_listener_after_push = False
        self.resume_wakeword_after_push = False
        self.current_operation: asyncio.Task | None = None
        self.stt_in_progress = False
        self.operation_canceling = False
        self.session_lock = asyncio.Lock()
        self.latest_frame = None
        self.login_face_count = 0
        self.face_check_running = False
        self.presence_check_running = False
        self.presence_missing_count = 0
        self.registration_dialog: FaceScanDialog | None = None
        self.registration_embeddings: list[np.ndarray] = []
        self.registration_scan_running = False
        self.recovery_dialog: FaceScanDialog | None = None
        self.recovery_face_count = 0
        self.recovery_scan_running = False
        self.account_dialog_open = False
        self.logout_in_progress = False
        self.shutdown_started = False
        self.closed = False
        self.startup_errors: list[str] = []

        self.preview_timer = QTimer()
        self.preview_timer.setInterval(80)
        self.preview_timer.timeout.connect(self._update_camera_preview)
        self.login_timer = QTimer()
        self.login_timer.setInterval(2_000)
        self.login_timer.timeout.connect(self._schedule_login_face_check)
        self.presence_timer = QTimer()
        self.presence_timer.setInterval(60_000)
        self.presence_timer.timeout.connect(self._schedule_presence_check)
        self.registration_timer = QTimer()
        self.registration_timer.setInterval(700)
        self.registration_timer.timeout.connect(self._schedule_registration_scan)
        self.recovery_timer = QTimer()
        self.recovery_timer.setInterval(700)
        self.recovery_timer.timeout.connect(self._schedule_recovery_scan)

        self.bridge.utterance.connect(self._on_utterance)
        self.bridge.voice_error.connect(self._on_voice_error)
        self.bridge.push_to_talk_pressed.connect(self._on_push_to_talk_pressed)
        self.bridge.push_to_talk_released.connect(self._on_push_to_talk_released)
        self.bridge.stop_requested.connect(self.stop_current_operation)
        self.window.login.sign_in_requested.connect(self.open_sign_in)
        self.window.login.register_requested.connect(self.open_registration_without_face)
        self.window.close_requested.connect(self._request_shutdown)
        self.window.chat.message_submitted.connect(self._on_typed_message)
        self.window.chat.folder_requested.connect(self.select_folder)
        self.window.chat.folder_cleared.connect(self.clear_folder)
        self.window.chat.profile_requested.connect(self.open_profile_menu)
        self.window.chat.toggle_requested.connect(self._on_toggle_requested)
        self.window.chat.voice_mode_changed.connect(self._on_voice_mode_changed)
        self.window.chat.manual_mic_requested.connect(self._on_manual_mic_requested)
        self.window.chat.stop_requested.connect(self.stop_current_operation)
        self.window.chat.attachment_requested.connect(self.save_attachment)
        self.window.settings.back_requested.connect(self._return_to_chat)

    async def start(self) -> None:
        self.startup_errors.extend(await self._prepare_login_services())
        try:
            await asyncio.to_thread(self.hotkeys.start)
        except Exception as error:
            self.startup_errors.append(f"เปิดปุ่ม F9 และ F10 ไม่สำเร็จ: {error}")
        self._refresh_settings()
        self.window.chat.set_voice_mode("normal")
        self.window.chat.set_mic_enabled(False)
        self.presence_timer.start()
        if self.state.camera_available:
            self.window.login.camera.setText("กำลังเปิดกล้อง...")
        self.window.showMaximized()

        # Models are ready before Login appears; only the camera is activated
        # after Qt has presented the page.
        await asyncio.sleep(0.05)
        camera_error = await self._open_login_camera()
        if camera_error:
            self.startup_errors.append(camera_error)
        self._refresh_settings()
        if self.startup_errors:
            QTimer.singleShot(
                0,
                lambda: self._show_error("\n".join(self.startup_errors)),
            )

    async def _prepare_login_services(self) -> list[str]:
        errors: list[str] = []
        camera, microphone, speaker = await asyncio.gather(
            asyncio.to_thread(HardwareManager.camera_available),
            asyncio.to_thread(HardwareManager.microphone_available),
            asyncio.to_thread(HardwareManager.speaker_available),
        )
        self.state.camera_available = camera
        self.state.microphone_available = microphone
        self.state.speaker_available = speaker
        self.state.camera_enabled = False
        self.state.microphone_enabled = False
        self.state.tts_enabled = False

        if camera:
            try:
                await asyncio.to_thread(self.face.load)
            except Exception as error:
                self.state.camera_available = False
                errors.append(f"โหลดระบบจดจำใบหน้าไม่สำเร็จ: {error}")

        if microphone:
            try:
                await asyncio.to_thread(self.stt.start)
            except Exception as error:
                self.state.microphone_available = False
                errors.append(f"โหลดระบบรับเสียงไม่สำเร็จ: {error}")
            if self.state.microphone_available:
                try:
                    await asyncio.to_thread(self.wakeword.start)
                    self.wakeword_ready = True
                except Exception as error:
                    errors.append(f"โหลดระบบคำปลุก Alexa ไม่สำเร็จ: {error}")
        else:
            await asyncio.to_thread(self.stt.close)

        if speaker:
            try:
                await self.audio_queue.start()
            except Exception as error:
                self.state.speaker_available = False
                errors.append(f"เตรียมระบบเสียงพูดไม่สำเร็จ: {error}")
        else:
            await self.audio_queue.close()
        return errors

    async def _open_login_camera(self) -> str | None:
        if not self.state.camera_available or self.shutdown_started:
            self.window.login.camera.setText("ไม่พบกล้อง")
            self.window.login.status.setText("ลงชื่อเข้าใช้ด้วยชื่อผู้ใช้และรหัสผ่าน")
            return None
        try:
            await asyncio.to_thread(self.face.open_camera)
            self.state.camera_enabled = True
            self.preview_timer.start()
            self.login_timer.start()
            self.window.login.status.setText("มองกล้องเพื่อเข้าสู่ระบบ")
            return None
        except Exception as error:
            self.state.camera_available = False
            self.state.camera_enabled = False
            self.window.login.camera.setText("ไม่พบกล้อง")
            return f"เปิดกล้องหน้าเข้าสู่ระบบไม่สำเร็จ: {error}"

    async def close(self) -> None:
        if self.closed:
            return
        self.preview_timer.stop()
        self.login_timer.stop()
        self.presence_timer.stop()
        self.registration_timer.stop()
        self.recovery_timer.stop()
        errors: list[str] = []
        try:
            self.hotkeys.close()
        except Exception as error:
            errors.append(str(error))
        if self.voice_listener is not None:
            try:
                await asyncio.to_thread(self.voice_listener.stop)
            except Exception as error:
                errors.append(str(error))
        if self.wakeword_listener is not None:
            try:
                await asyncio.to_thread(self.wakeword_listener.stop)
            except Exception as error:
                errors.append(str(error))
        try:
            await asyncio.to_thread(self.wakeword.close)
        except Exception as error:
            errors.append(str(error))
        try:
            await asyncio.to_thread(self.manual_recorder.close)
        except Exception as error:
            errors.append(str(error))
        try:
            await asyncio.to_thread(self.face.close)
        except Exception as error:
            errors.append(str(error))
        try:
            await asyncio.to_thread(self.stt.close)
        except Exception as error:
            errors.append(str(error))
        try:
            await self.audio_queue.close()
        except Exception as error:
            errors.append(str(error))
        try:
            await self.controller.close()
        except Exception as error:
            errors.append(str(error))
        try:
            self.attachment_cache.cleanup()
        except Exception as error:
            errors.append(str(error))
        try:
            self._reset_input_attachment_cache()
        except Exception as error:
            errors.append(str(error))
        self.closed = True
        if errors:
            print("SHUTDOWN WARNING: " + " | ".join(errors))

    def _request_shutdown(self) -> None:
        if self.shutdown_started:
            return
        self.shutdown_started = True
        # Release the camera immediately. The remaining services are closed
        # asynchronously while the Qt event loop is still alive.
        self.preview_timer.stop()
        self.login_timer.stop()
        self.presence_timer.stop()
        self.registration_timer.stop()
        self.recovery_timer.stop()
        self.face.close_camera()
        asyncio.create_task(self._shutdown_and_close_window())

    async def _shutdown_and_close_window(self) -> None:
        try:
            await self.close()
        finally:
            self.window.finish_close()

    def _start_voice_listener(self) -> None:
        if self.voice_listener is None:
            self.voice_listener = VoiceListener(
                on_utterance=self.bridge.utterance.emit,
                can_listen=lambda: (
                    self.state.logged_in
                    and self.state.microphone_enabled
                    and self.state.voice_mode == "automatic"
                    and not self.state.assistant_busy
                ),
                on_error=lambda error: self.bridge.voice_error.emit(str(error)),
            )
        self.voice_listener.start()

    def _start_wakeword_listener(self) -> None:
        if not self.wakeword_ready:
            return
        if self.wakeword_listener is None:
            self.wakeword_listener = WakeWordListener(
                service=self.wakeword,
                on_command=self.bridge.utterance.emit,
                can_listen=lambda: (
                    self.state.logged_in
                    and self.state.microphone_enabled
                    and self.state.voice_mode == "normal"
                    and not self.state.assistant_busy
                    and not self.manual_recorder.recording
                    and not self.push_to_talk_recording
                ),
                on_error=lambda error: self.bridge.voice_error.emit(str(error)),
            )
        self.wakeword_listener.start()

    def _update_camera_preview(self) -> None:
        if not self.state.camera_enabled:
            return
        frame = self.face.read_frame()
        if frame is None:
            return
        self.latest_frame = frame
        pixmap = numpy_to_pixmap(self.face.frame_to_rgb(frame))
        self.window.login.show_frame(pixmap)
        if self.registration_dialog is not None and self.registration_dialog.isVisible():
            self.registration_dialog.show_frame(pixmap)
        if self.recovery_dialog is not None and self.recovery_dialog.isVisible():
            self.recovery_dialog.show_frame(pixmap)

    def _schedule_login_face_check(self) -> None:
        if (
            self.face_check_running
            or self.state.logged_in
            or self.state.assistant_busy
            or not self.state.camera_enabled
            or self.registration_dialog is not None
            or self.recovery_dialog is not None
            or self.account_dialog_open
        ):
            return
        frame = None if self.latest_frame is None else self.latest_frame.copy()
        self.face_check_running = True
        asyncio.create_task(self._login_face_check(frame))

    async def _login_face_check(self, frame) -> None:
        try:
            if self.login_face_count < 2:
                detected = await asyncio.to_thread(self.face.has_face, frame)
                if self.account_dialog_open:
                    self.login_face_count = 0
                    return
                if not detected:
                    self.login_face_count = 0
                    self.window.login.status.setText("มองกล้องเพื่อเข้าสู่ระบบ")
                    return
                self.login_face_count += 1
                self.window.login.status.setText(
                    f"กำลังตรวจสอบใบหน้า {self.login_face_count} จาก 3"
                )
                return

            # Only the third consecutive detection creates an embedding and
            # compares it with registered profiles.
            result = await asyncio.to_thread(self.face.extract_largest, frame)
            if self.account_dialog_open:
                self.login_face_count = 0
                return
            if not result.detected:
                self.login_face_count = 0
                self.window.login.status.setText("มองกล้องเพื่อเข้าสู่ระบบ")
                return
            self.window.login.status.setText("กำลังตรวจสอบใบหน้า 3 จาก 3")
            self.login_face_count = 0
            user = await asyncio.to_thread(self.face.recognize, result.embedding)
            if user is not None:
                self._login(user.id, user.username, user.nickname)
            else:
                self.window.login.status.setText("ไม่พบบัญชีสำหรับใบหน้านี้")
                self.open_registration_with_face(result.embedding)
        except Exception as error:
            self.login_face_count = 0
            self._show_error(f"ตรวจสอบใบหน้าไม่สำเร็จ: {error}")
        finally:
            self.face_check_running = False

    def _schedule_presence_check(self) -> None:
        if (
            self.presence_check_running
            or not self.state.logged_in
            or self.state.assistant_busy
            or not self.state.camera_enabled
        ):
            return
        frame = None if self.latest_frame is None else self.latest_frame.copy()
        self.presence_check_running = True
        asyncio.create_task(self._presence_check(frame))

    async def _presence_check(self, frame) -> None:
        try:
            result = await asyncio.to_thread(self.face.extract_largest, frame)
            if not result.detected:
                return
            user = await asyncio.to_thread(self.face.recognize, result.embedding)
            if user is not None and user.id == self.state.current_user_id:
                self.presence_missing_count = 0
                return
            self.presence_missing_count += 1
            if self.presence_missing_count >= 3:
                self.logout()
        except Exception:
            # Camera and recognition errors are not evidence that the user left.
            return
        finally:
            self.presence_check_running = False

    def open_sign_in(self) -> None:
        if self.account_dialog_open:
            return
        camera_was_enabled = self._suspend_camera_for_account_dialog()
        self.account_dialog_open = True
        dialog = FormDialog(
            "ลงชื่อเข้าใช้",
            [("ชื่อผู้ใช้", False), ("รหัสผ่าน", True)],
            self.window,
            secondary_text="ลืมรหัสผ่าน",
        )
        forgot_password = False

        def submit(values: list[str]) -> None:
            user = self.database.authenticate(values[0], values[1])
            if user is None:
                dialog.show_error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
                return
            dialog.accept()
            self._login(user.id, user.username, user.nickname)

        dialog.submitted.connect(submit)

        def request_password_recovery() -> None:
            nonlocal forgot_password
            forgot_password = True
            dialog.reject()

        dialog.secondary_requested.connect(request_password_recovery)
        try:
            dialog.exec()
        finally:
            self.account_dialog_open = False
            self._restore_camera_after_account_dialog(camera_was_enabled)
        if forgot_password:
            QTimer.singleShot(0, self.open_password_recovery)

    def open_password_recovery(self) -> None:
        if self.recovery_dialog is not None or self.account_dialog_open:
            return
        if not self.state.camera_enabled:
            self.window.login.status.setText(
                "ไม่สามารถรีเซ็ตรหัสผ่านได้ เพราะไม่พบกล้องที่เปิดใช้งาน"
            )
            return
        if not self.database.has_face_profiles():
            self.window.login.status.setText(
                "ไม่มีบัญชีที่ลงทะเบียนใบหน้าสำหรับรีเซ็ตรหัสผ่าน"
            )
            return

        self.recovery_face_count = 0
        dialog = FaceScanDialog(
            self.window,
            title_text="ยืนยันใบหน้า",
            status_text="มองกล้องเพื่อยืนยันตัวตน",
            show_next_button=False,
            show_retry_button=False,
        )
        self.recovery_dialog = dialog
        dialog.finished.connect(self._recovery_closed)
        self.recovery_timer.start()
        dialog.open()

    def _schedule_recovery_scan(self) -> None:
        if (
            self.recovery_dialog is None
            or self.recovery_scan_running
            or not self.state.camera_enabled
        ):
            return
        frame = None if self.latest_frame is None else self.latest_frame.copy()
        self.recovery_scan_running = True
        asyncio.create_task(self._recovery_scan(frame))

    async def _recovery_scan(self, frame) -> None:
        try:
            if self.recovery_face_count < 2:
                detected = await asyncio.to_thread(self.face.has_face, frame)
                if not detected:
                    self.recovery_face_count = 0
                    if self.recovery_dialog is not None:
                        self.recovery_dialog.status.setText("มองกล้องเพื่อยืนยันตัวตน")
                    return
                self.recovery_face_count += 1
                if self.recovery_dialog is not None:
                    self.recovery_dialog.status.setText(
                        f"กำลังยืนยันใบหน้า {self.recovery_face_count} จาก 3"
                    )
                return

            result = await asyncio.to_thread(self.face.extract_largest, frame)
            if not result.detected:
                self.recovery_face_count = 0
                if self.recovery_dialog is not None:
                    self.recovery_dialog.status.setText("มองกล้องเพื่อยืนยันตัวตน")
                return

            self.recovery_face_count = 0
            user = await asyncio.to_thread(self.face.recognize, result.embedding)
            if user is None:
                if self.recovery_dialog is not None:
                    self.recovery_dialog.status.setText("ไม่พบใบหน้าที่ลงทะเบียนไว้")
                return

            self.recovery_timer.stop()
            if self.recovery_dialog is not None:
                self.recovery_dialog.accept()
            QTimer.singleShot(0, lambda: self._open_reset_password_form(user))
        except Exception as error:
            self._show_error(f"ยืนยันใบหน้าไม่สำเร็จ: {error}")
        finally:
            self.recovery_scan_running = False

    def _recovery_closed(self) -> None:
        self.recovery_timer.stop()
        self.recovery_dialog = None
        self.recovery_face_count = 0
        self.recovery_scan_running = False

    def _open_reset_password_form(self, user) -> None:
        camera_was_enabled = self._suspend_camera_for_account_dialog()
        self.account_dialog_open = True
        dialog = FormDialog(
            f"ตั้งรหัสผ่านใหม่สำหรับ {user.nickname}",
            [("รหัสผ่านใหม่", True), ("ยืนยันรหัสผ่านใหม่", True)],
            self.window,
        )

        def submit(values: list[str]) -> None:
            if values[0] != values[1]:
                dialog.show_error("รหัสผ่านใหม่ไม่ตรงกัน")
                return
            try:
                self.database.reset_password(user.id, values[0])
            except ValueError as error:
                dialog.show_error(str(error))
                return
            dialog.accept()
            self.window.login.status.setText(
                "เปลี่ยนรหัสผ่านสำเร็จ กรุณาลงชื่อเข้าใช้"
            )

        dialog.submitted.connect(submit)
        try:
            dialog.exec()
        finally:
            self.account_dialog_open = False
            self._restore_camera_after_account_dialog(camera_was_enabled)

    def open_registration_without_face(self) -> None:
        self._open_registration_form([])

    def open_registration_with_face(self, embedding: np.ndarray) -> None:
        self._open_registration_form([embedding], includes_face=True)

    def _schedule_registration_scan(self) -> None:
        if (
            self.registration_dialog is None
            or self.registration_scan_running
            or self.state.assistant_busy
        ):
            return
        frame = None if self.latest_frame is None else self.latest_frame.copy()
        self.registration_scan_running = True
        asyncio.create_task(self._registration_scan(frame))

    async def _registration_scan(self, frame) -> None:
        try:
            result = await asyncio.to_thread(self.face.extract_for_enrollment, frame)
            if not result.detected or result.embedding is None:
                self.registration_embeddings.clear()
                if self.registration_dialog is not None:
                    self.registration_dialog.status.setText(
                        result.reason or "มองกล้องเพื่อสแกนใบหน้า"
                    )
                return
            self.registration_embeddings.append(result.embedding)
            if self.registration_dialog is not None:
                self.registration_dialog.status.setText(
                    f"กำลังสแกนใบหน้า {len(self.registration_embeddings)} จาก 3"
                )
            if len(self.registration_embeddings) >= 3 and self.registration_dialog is not None:
                self.registration_timer.stop()
                completed_pixmap = numpy_to_pixmap(self.face.frame_to_rgb(frame))
                self.registration_dialog.set_complete(completed_pixmap)
        except Exception as error:
            self._show_error(f"สแกนใบหน้าไม่สำเร็จ: {error}")
        finally:
            self.registration_scan_running = False

    def _registration_closed(self) -> None:
        self.registration_timer.stop()
        self.registration_dialog = None
        self.registration_scan_running = False

    def _open_registration_form(
        self,
        embeddings: list[np.ndarray],
        includes_face: bool = False,
    ) -> None:
        if self.account_dialog_open:
            return
        camera_was_enabled = self._suspend_camera_for_account_dialog()
        self.account_dialog_open = True
        dialog = FormDialog(
            "สมัครบัญชีด้วยใบหน้า" if includes_face else "สมัครบัญชี",
            [
                ("ชื่อผู้ใช้ (ภาษาอังกฤษและตัวเลข)", False),
                ("ชื่อเล่น", False),
                ("รหัสผ่าน", True),
                ("ยืนยันรหัสผ่าน", True),
            ],
            self.window,
        )

        def submit(values: list[str]) -> None:
            validation = self.database.validate_new_user(
                values[0],
                values[1],
                values[2],
            )
            field_indexes = {"username": 0, "nickname": 1, "password": 2}
            field_errors = {
                field_indexes[name]: message
                for name, message in validation.items()
            }
            if values[2] != values[3]:
                field_errors[3] = "รหัสผ่านไม่ตรงกัน"
            if field_errors:
                dialog.show_errors(field_errors)
                return
            try:
                user = self.database.create_user(
                    values[0],
                    values[1],
                    values[2],
                    embeddings,
                )
            except ValueError as error:
                dialog.show_error(str(error))
                return
            dialog.accept()
            self._login(user.id, user.username, user.nickname)

        dialog.submitted.connect(submit)
        try:
            dialog.exec()
        finally:
            self.account_dialog_open = False
            self._restore_camera_after_account_dialog(camera_was_enabled)

    def _suspend_camera_for_account_dialog(self) -> bool:
        was_enabled = self.state.camera_enabled
        if not was_enabled:
            return False
        self.preview_timer.stop()
        self.login_timer.stop()
        self.face.close_camera()
        self.latest_frame = None
        self.login_face_count = 0
        self.state.camera_enabled = False
        return True

    def _restore_camera_after_account_dialog(self, should_restore: bool) -> None:
        if (
            not should_restore
            or self.shutdown_started
            or self.state.logged_in
            or not self.state.camera_available
        ):
            return
        try:
            self.face.open_camera()
            self.state.camera_enabled = True
            self.preview_timer.start()
            self.login_timer.start()
        except Exception as error:
            self.state.camera_available = False
            self.state.camera_enabled = False
            self.window.login.camera.setText("ไม่พบกล้อง")
            self._show_error(f"เปิดกล้องกลับไม่สำเร็จ: {error}")
        finally:
            self._refresh_settings()

    def _login(self, user_id: int, username: str, nickname: str) -> None:
        self.state.login(user_id, username, nickname)
        self.state.voice_mode = "normal"
        self.login_face_count = 0
        self.presence_missing_count = 0
        self.window.chat.clear_messages()
        self.window.chat.set_folder(None)
        self.window.chat.set_nickname(nickname)
        self.window.chat.set_voice_mode("normal")
        self.window.show_chat()
        asyncio.create_task(self._enter_chat_session())

    def logout(self) -> None:
        if self.logout_in_progress:
            return
        self.logout_in_progress = True
        asyncio.create_task(self._logout_to_login())

    async def _logout_to_login(self) -> None:
        dialog = LoadingDialog(
            "กำลังออกจากระบบ",
            "กำลังตรวจสอบอุปกรณ์ก่อนกลับหน้าเข้าสู่ระบบ...",
            self.window,
        )
        dialog.show()
        errors: list[str] = []
        try:
            if self.current_operation is not None and not self.current_operation.done():
                self.current_operation.cancel()
            await self._leave_chat_session()
            self.preview_timer.stop()
            self.login_timer.stop()
            await asyncio.to_thread(self.face.close_camera)
            self.state.logout()
            self.controller.set_allowed_directory(None)
            self.presence_missing_count = 0
            self.latest_frame = None
            self.window.chat.clear_messages()
            self.window.chat.set_folder(None)
            self.window.chat.set_nickname("")
            errors.extend(await self._prepare_login_services())
            self._refresh_settings()
            self.window.login.camera.setText(
                "กำลังเปิดกล้อง..."
                if self.state.camera_available
                else "ไม่พบกล้อง"
            )
            self.window.show_login()
            await asyncio.sleep(0.05)
            camera_error = await self._open_login_camera()
            if camera_error:
                errors.append(camera_error)
            self._refresh_settings()
        finally:
            dialog.close()
            self.logout_in_progress = False
        if errors:
            self.window.login.status.setText("\n".join(errors))

    async def _enter_chat_session(self) -> None:
        async with self.session_lock:
            if not self.state.logged_in or self.shutdown_started:
                return
            dialog = LoadingDialog("กำลังเตรียมระบบ", "กำลังเริ่มเซสชัน AI ใหม่...", self.window)
            dialog.show()
            errors: list[str] = []
            user_id = self.state.current_user_id
            try:
                await self.controller.reset_conversation(start=True)
            except Exception as error:
                errors.append(f"เริ่มเซสชัน AI ไม่สำเร็จ: {error}")

            try:
                settings = await asyncio.to_thread(
                    self.database.get_device_settings,
                    user_id,
                )
                self.state.voice_mode = "normal"
                self.window.chat.set_voice_mode("normal")
                self.login_timer.stop()

                if settings.camera_enabled and self.state.camera_available:
                    await asyncio.to_thread(self.face.open_camera)
                    self.state.camera_enabled = True
                    self.preview_timer.start()
                else:
                    self.preview_timer.stop()
                    await asyncio.to_thread(self.face.close_camera)
                    self.state.camera_enabled = False

                self.state.microphone_enabled = (
                    settings.microphone_enabled and self.state.microphone_available
                )
                self.state.tts_enabled = (
                    settings.tts_enabled and self.state.speaker_available
                )
            except Exception as error:
                errors.append(f"โหลดการตั้งค่าอุปกรณ์ไม่สำเร็จ: {error}")

            dialog.close()
            self._refresh_settings()
            if (
                self.state.logged_in
                and self.state.microphone_enabled
                and self.state.voice_mode == "normal"
            ):
                self._start_wakeword_listener()
            if errors and self.state.logged_in:
                self._show_error("\n".join(errors))

    async def _leave_chat_session(self) -> None:
        async with self.session_lock:
            try:
                await self.audio_queue.cancel()
                if self.voice_listener is not None:
                    await asyncio.to_thread(self.voice_listener.stop)
                if self.wakeword_listener is not None:
                    await asyncio.to_thread(self.wakeword_listener.stop)
                await asyncio.to_thread(self.manual_recorder.close)
                await self.controller.reset_conversation(start=False)
            except Exception as error:
                print(f"LOGOUT WARNING: {error}")
            finally:
                self.state.microphone_enabled = False
                self.state.tts_enabled = False
                self.push_to_talk_held = False
                self.push_to_talk_recording = False
                self.resume_voice_listener_after_push = False
                self.resume_wakeword_after_push = False
                self.current_operation = None
                self._reset_attachment_cache()
                self._reset_input_attachment_cache()
                self._refresh_settings()

    def _on_typed_message(self, text: str, attachments: list[str]) -> None:
        if self.current_operation is not None and not self.current_operation.done():
            return
        self.current_operation = asyncio.create_task(
            self.process_message(text, attachments=attachments)
        )
        self.current_operation.add_done_callback(self._operation_finished)

    def _on_utterance(self, audio) -> None:
        if self.state.assistant_busy or not self.state.logged_in:
            return
        self.state.assistant_busy = True
        self.stt_in_progress = True
        self.window.chat.set_busy(True)
        self.stt.prepare_transcription()
        self.current_operation = asyncio.create_task(self._transcribe_and_process(audio))
        self.current_operation.add_done_callback(self._operation_finished)

    async def _transcribe_and_process(self, audio) -> None:
        failed = False
        try:
            self.window.chat.set_busy(True, "กำลังแปลงเสียงเป็นข้อความ")
            text = (await asyncio.to_thread(self.stt.transcribe_audio, audio)).strip()
            self.stt_in_progress = False
            if not text:
                return
            if self.stt.is_shutdown_command(text):
                self.window.close()
                return
            await self.process_message(text, busy_already=True)
        except Exception as error:
            print(f"STT ERROR: {error}")
            failed = True
        finally:
            self.stt_in_progress = False
            if self.state.assistant_busy and not self.operation_canceling:
                self.state.assistant_busy = False
                self.window.chat.set_busy(False)
            if failed and not self.operation_canceling:
                self.window.chat.show_activity_error("แปลงเสียงเป็นข้อความล้มเหลว")

    async def process_message(
        self,
        text: str,
        busy_already: bool = False,
        attachments: list[str] | None = None,
    ) -> None:
        if self.state.assistant_busy and not busy_already:
            return
        self.state.assistant_busy = True
        self.window.chat.set_busy(True, "AI กำลังประมวลผล")
        source_attachments: list[Path] = []
        staged_attachments: list[Path] = []
        if text:
            self.window.chat.add_message(text, "user")
        try:
            source_attachments = self._validate_input_attachments(attachments or [])
            self.window.chat.add_user_attachments(source_attachments)
            if not self.controller.awaiting_user_input:
                self._reset_input_attachment_cache()
                self.input_attachment_cache = tempfile.TemporaryDirectory(
                    prefix="ai_pc_input_attachments_"
                )
            if self.input_attachment_cache is not None:
                staged_attachments = self._stage_input_attachments(
                    source_attachments,
                    Path(self.input_attachment_cache.name).resolve(),
                )
            effective_text = text.strip() or "โปรดตรวจสอบไฟล์ที่แนบมา"
            if self.controller.awaiting_user_input:
                documents_before = self._document_snapshot()
                worker = await self.controller.continue_task(
                    self._message_with_attachment_paths(
                        effective_text,
                        staged_attachments,
                    ),
                    progress_callback=self._show_admin_progress,
                )
                self.window.chat.add_message(worker.response, "result")
                self._show_created_documents(documents_before, worker.status)
                self._speak(worker.response)
            else:
                chat = await self.controller.generate_chat(
                    effective_text,
                    attachments=staged_attachments,
                )
                self.window.chat.add_message(chat.response, "assistant")
                self._speak(chat.response)
                documents_before = self._document_snapshot()
                self.controller.set_temporary_attachment_directory(
                    Path(self.input_attachment_cache.name)
                    if (
                        chat.type == "task"
                        and self.input_attachment_cache is not None
                    )
                    else None
                )
                worker = await self.controller.execute_task(
                    chat,
                    progress_callback=self._show_admin_progress,
                )
                if worker is not None:
                    self.window.chat.add_message(worker.response, "result")
                    self._show_created_documents(documents_before, worker.status)
                    self._speak(worker.response)
            await self.controller.rotate_chat_if_ready()
            if self.state.tts_enabled:
                self.window.chat.set_busy(True, "กำลังสร้างเสียงตอบกลับ")
                await self.audio_queue.wait_until_idle()
        except Exception as error:
            self._show_error(f"เกิดข้อผิดพลาด: {error}")
        finally:
            if not self.controller.awaiting_user_input:
                self._reset_input_attachment_cache()
            if not self.operation_canceling:
                self.state.assistant_busy = False
                self.window.chat.set_busy(False)

    def _validate_input_attachments(self, paths: list[str]) -> list[Path]:
        validated: list[Path] = []
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if (
                not path.is_file()
                or path.is_symlink()
                or path.suffix.lower() not in self.INPUT_ATTACHMENT_SUFFIXES
            ):
                raise ValueError(f"ไม่รองรับไฟล์ {path.name}")
            if path.stat().st_size > self.MAX_INPUT_ATTACHMENT_SIZE:
                raise ValueError(f"ไฟล์ {path.name} มีขนาดเกิน 25 MB")
            validated.append(path)
        return validated

    @staticmethod
    def _stage_input_attachments(paths: list[Path], directory: Path) -> list[Path]:
        staged: list[Path] = []
        directory.mkdir(parents=True, exist_ok=True)
        for source in paths:
            destination = directory / source.name
            counter = 2
            while destination.exists():
                destination = directory / f"{source.stem}_{counter}{source.suffix}"
                counter += 1
            shutil.copy2(source, destination)
            staged.append(destination.resolve())
        return staged

    def _reset_input_attachment_cache(self) -> None:
        if self.input_attachment_cache is not None:
            self.input_attachment_cache.cleanup()
            self.input_attachment_cache = None

    @staticmethod
    def _message_with_attachment_paths(text: str, paths: list[Path]) -> str:
        if not paths:
            return text
        attached = "\n".join(f"- {path}" for path in paths)
        return f"{text}\n\nไฟล์ที่ผู้ใช้แนบมา:\n{attached}"

    def _show_admin_progress(self, message: str) -> None:
        self.window.chat.add_message(message, "result")
        self._speak(message)

    def _document_snapshot(self) -> dict[Path, tuple[int, int]]:
        documents = (self.project_root / "documents").resolve()
        snapshot: dict[Path, tuple[int, int]] = {}
        candidates = list(documents.rglob("*")) if documents.is_dir() else []
        candidates.extend(self.project_root.glob("*"))
        for path in candidates:
            try:
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or path.suffix.lower() not in self.ATTACHMENT_SUFFIXES
                ):
                    continue
                stat = path.stat()
            except OSError:
                continue
            snapshot[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
        return snapshot

    def _show_created_documents(
        self,
        before: dict[Path, tuple[int, int]],
        worker_status: str,
    ) -> None:
        if worker_status != "completed":
            return
        after = self._document_snapshot()
        changed = sorted(
            (path for path, signature in after.items() if before.get(path) != signature),
            key=lambda path: path.name.casefold(),
        )
        staged: list[Path] = []
        for path in changed:
            source = self._move_root_attachment(path)
            destination = self._unique_attachment_cache_path(source.name)
            shutil.copy2(source, destination)
            staged.append(destination)
        for path in staged:
            self.window.chat.add_attachment(path)
        if staged:
            self._clear_documents()

    def _unique_attachment_cache_path(self, filename: str) -> Path:
        original = self.attachment_cache_path / filename
        destination = original
        counter = 2
        while destination.exists():
            destination = (
                self.attachment_cache_path
                / f"{original.stem}_{counter}{original.suffix}"
            )
            counter += 1
        return destination

    def _clear_documents(self) -> None:
        documents = (self.project_root / "documents").resolve()
        expected = self.project_root.resolve() / "documents"
        if documents != expected:
            raise RuntimeError("ตำแหน่งโฟลเดอร์ documents ไม่ถูกต้อง")
        documents.mkdir(parents=True, exist_ok=True)
        for child in documents.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)

    def _reset_attachment_cache(self) -> None:
        self.attachment_cache.cleanup()
        self.attachment_cache = tempfile.TemporaryDirectory(
            prefix="ai_pc_attachments_"
        )
        self.attachment_cache_path = Path(self.attachment_cache.name).resolve()

    def _move_root_attachment(self, path: Path) -> Path:
        project_root = self.project_root.resolve()
        source = path.resolve()
        if source.parent != project_root:
            return source

        documents = (project_root / "documents").resolve()
        documents.mkdir(parents=True, exist_ok=True)
        destination = documents / source.name
        counter = 2
        while destination.exists():
            destination = documents / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        return Path(shutil.move(str(source), str(destination))).resolve()

    def save_attachment(self, source_path: str) -> None:
        source = Path(source_path).resolve()
        project_root = self.project_root.resolve()
        documents = (self.project_root / "documents").resolve()
        in_project = source.parent == project_root or documents in source.parents
        in_cache = source.parent == self.attachment_cache_path
        if not in_project and not in_cache:
            self._show_error("ไม่สามารถบันทึกไฟล์จากตำแหน่งนี้ได้")
            return
        if (
            not source.is_file()
            or source.is_symlink()
            or source.suffix.lower() not in self.ATTACHMENT_SUFFIXES
        ):
            self._show_error("ไม่พบไฟล์ที่ต้องการบันทึก")
            return

        downloads = Path.home() / "Downloads"
        initial = (downloads if downloads.is_dir() else Path.home()) / source.name
        destination, _ = QFileDialog.getSaveFileName(
            self.window,
            "บันทึกไฟล์เป็น",
            str(initial),
            f"ไฟล์ {source.suffix.upper()} (*{source.suffix});;ไฟล์ทั้งหมด (*)",
        )
        if not destination:
            return
        target = Path(destination).resolve()
        if target == source:
            return
        try:
            shutil.copy2(source, target)
        except OSError as error:
            self._show_error(f"บันทึกไฟล์ไม่สำเร็จ: {error}")

    def _speak(self, text: str) -> None:
        if self.state.tts_enabled:
            self.audio_queue.enqueue(text)

    def select_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self.window, "เลือกโฟลเดอร์")
        if path:
            self.state.allowed_folder = path
            self.controller.set_allowed_directory(path)
            self.window.chat.set_folder(path)

    def clear_folder(self) -> None:
        self.state.allowed_folder = None
        self.controller.set_allowed_directory(None)
        self.window.chat.set_folder(None)

    def open_profile_menu(self, anchor) -> None:
        self.window.show_profile_menu(
            anchor,
            {
                "rename": self.rename_user,
                "face": self.manage_face,
                "password": self.change_password,
                "settings": self.window.show_settings,
                "logout": self.logout,
            },
        )

    def _operation_finished(self, task: asyncio.Task) -> None:
        if self.current_operation is task:
            self.current_operation = None
        if not task.cancelled():
            try:
                task.exception()
            except Exception:
                pass

    def stop_current_operation(self) -> None:
        if self.operation_canceling:
            return
        self.operation_canceling = True
        self.window.chat.set_busy(True, "กำลังหยุดการทำงาน")
        asyncio.create_task(self._stop_current_operation())

    async def _stop_current_operation(self) -> None:
        task = self.current_operation
        was_transcribing = self.stt_in_progress
        self.push_to_talk_held = False
        self.push_to_talk_recording = False
        self.stt.request_cancel()
        if self.manual_recorder.recording:
            await asyncio.to_thread(self.manual_recorder.stop)
            self.window.chat.set_manual_recording(False)
        if task is not None and not task.done():
            task.cancel()
        cancellations = [
            self.audio_queue.cancel(),
            self.controller.cancel_pending_task(),
        ]
        if was_transcribing:
            cancellations.append(asyncio.to_thread(self.stt.cancel_current))
        try:
            cleanup_tasks = {
                asyncio.create_task(cancellation)
                for cancellation in cancellations
            }
            _done, pending_cleanup = await asyncio.wait(
                cleanup_tasks,
                timeout=5,
            )
            if pending_cleanup:
                print("STOP WARNING: cleanup ใช้เวลานานเกิน 5 วินาที")
                for cleanup_task in pending_cleanup:
                    cleanup_task.cancel()
            if task is not None:
                done, _pending = await asyncio.wait({task}, timeout=2)
                if not done:
                    print("STOP WARNING: task ยังไม่หยุดภายใน 2 วินาที")
                elif not task.cancelled():
                    try:
                        task.exception()
                    except Exception:
                        pass
        finally:
            if self.current_operation is task:
                self.current_operation = None
            self.state.assistant_busy = False
            self.stt_in_progress = False
            self.operation_canceling = False
            self.window.chat.set_busy(False)
            if (
                self.resume_voice_listener_after_push
                and self.state.voice_mode == "automatic"
                and self.state.microphone_enabled
            ):
                self._start_voice_listener()
            self.resume_voice_listener_after_push = False
            if was_transcribing:
                self.window.chat.show_activity_error("แปลงเสียงเป็นข้อความล้มเหลว")

    def _on_voice_mode_changed(self, mode: str) -> None:
        if mode not in {"automatic", "normal"} or mode == self.state.voice_mode:
            return
        asyncio.create_task(self._set_voice_mode(mode))

    def _return_to_chat(self) -> None:
        self.window.show_chat()
        if self.state.voice_mode != "normal":
            asyncio.create_task(self._set_voice_mode("normal"))
        else:
            self.window.chat.set_voice_mode("normal")

    async def _set_voice_mode(self, mode: str) -> None:
        if self.manual_recorder.recording:
            await asyncio.to_thread(self.manual_recorder.stop)
            self.window.chat.set_manual_recording(False)
        if self.voice_listener is not None:
            await asyncio.to_thread(self.voice_listener.stop)
        if self.wakeword_listener is not None:
            await asyncio.to_thread(self.wakeword_listener.stop)
        self.state.voice_mode = mode
        self.window.chat.set_voice_mode(mode)
        if mode == "automatic" and self.state.microphone_enabled:
            self._start_voice_listener()
        elif mode == "normal" and self.state.microphone_enabled:
            self._start_wakeword_listener()

    def _on_manual_mic_requested(self, start: bool) -> None:
        if (
            not self.state.logged_in
            or not self.state.microphone_enabled
            or self.state.voice_mode != "normal"
            or self.state.assistant_busy
            or self.push_to_talk_recording
        ):
            return
        if start:
            asyncio.create_task(self._start_manual_recording())
            return

        audio = self.manual_recorder.stop()
        self.window.chat.set_manual_recording(False)
        if audio.size == 0:
            self._start_wakeword_listener()
            return
        self.state.assistant_busy = True
        self.stt_in_progress = True
        self.window.chat.set_busy(True, "กำลังแปลงเสียงเป็นข้อความ")
        self.stt.prepare_transcription()
        self.current_operation = asyncio.create_task(self._transcribe_to_input(audio))
        self.current_operation.add_done_callback(self._operation_finished)

    async def _start_manual_recording(self) -> None:
        if self.wakeword_listener is not None:
            await asyncio.to_thread(self.wakeword_listener.stop)
        if (
            not self.state.logged_in
            or not self.state.microphone_enabled
            or self.state.voice_mode != "normal"
            or self.state.assistant_busy
        ):
            return
        try:
            await asyncio.to_thread(self.manual_recorder.start)
            self.window.chat.set_manual_recording(True)
        except Exception as error:
            self._start_wakeword_listener()
            self._show_error(f"เปิดไมโครโฟนไม่สำเร็จ: {error}")

    def _on_push_to_talk_pressed(self) -> None:
        if self.push_to_talk_held:
            return
        self.push_to_talk_held = True
        asyncio.create_task(self._start_push_to_talk())

    def _on_push_to_talk_released(self) -> None:
        self.push_to_talk_held = False
        asyncio.create_task(self._finish_push_to_talk())

    async def _start_push_to_talk(self) -> None:
        if (
            not self.push_to_talk_held
            or not self.state.logged_in
            or not self.state.microphone_enabled
            or self.state.assistant_busy
            or self.operation_canceling
            or self.manual_recorder.recording
        ):
            return

        self.resume_voice_listener_after_push = bool(
            self.voice_listener is not None and self.voice_listener.running
        )
        self.resume_wakeword_after_push = bool(
            self.wakeword_listener is not None and self.wakeword_listener.running
        )
        if self.resume_voice_listener_after_push:
            await asyncio.to_thread(self.voice_listener.stop)
        if self.resume_wakeword_after_push:
            await asyncio.to_thread(self.wakeword_listener.stop)
        if not self.push_to_talk_held:
            if self.resume_voice_listener_after_push:
                self._start_voice_listener()
            if self.resume_wakeword_after_push:
                self._start_wakeword_listener()
            self.resume_voice_listener_after_push = False
            self.resume_wakeword_after_push = False
            return
        try:
            await asyncio.to_thread(self.manual_recorder.start)
            self.push_to_talk_recording = True
            self.window.chat.set_manual_recording(True)
            if not self.push_to_talk_held or self.operation_canceling:
                await asyncio.to_thread(self.manual_recorder.stop)
                self.push_to_talk_recording = False
                self.window.chat.set_manual_recording(False)
                if self.resume_voice_listener_after_push:
                    self._start_voice_listener()
                if self.resume_wakeword_after_push:
                    self._start_wakeword_listener()
                self.resume_voice_listener_after_push = False
                self.resume_wakeword_after_push = False
        except Exception as error:
            self.push_to_talk_recording = False
            self.window.chat.set_manual_recording(False)
            if self.resume_voice_listener_after_push:
                self._start_voice_listener()
            if self.resume_wakeword_after_push:
                self._start_wakeword_listener()
            self.resume_voice_listener_after_push = False
            self.resume_wakeword_after_push = False
            self._show_error(f"เปิดไมโครโฟนไม่สำเร็จ: {error}")

    async def _finish_push_to_talk(self) -> None:
        if not self.push_to_talk_recording:
            return
        self.push_to_talk_recording = False
        resume_voice_listener = self.resume_voice_listener_after_push
        resume_wakeword = self.resume_wakeword_after_push
        self.resume_voice_listener_after_push = False
        self.resume_wakeword_after_push = False
        try:
            audio = await asyncio.to_thread(self.manual_recorder.stop)
        except Exception as error:
            self._show_error(f"หยุดบันทึกเสียงไม่สำเร็จ: {error}")
            audio = None
        finally:
            self.window.chat.set_manual_recording(False)
        if audio is not None and audio.size:
            self._on_utterance(audio)
        if resume_voice_listener:
            self._start_voice_listener()
        if resume_wakeword:
            self._start_wakeword_listener()

    async def _transcribe_to_input(self, audio) -> None:
        failed = False
        try:
            text = (await asyncio.to_thread(self.stt.transcribe_audio, audio)).strip()
            self.stt_in_progress = False
            if text:
                self.window.chat.append_transcript(text)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"STT ERROR: {error}")
            failed = True
        finally:
            self.stt_in_progress = False
            if not self.operation_canceling:
                self.state.assistant_busy = False
                self.window.chat.set_busy(False)
                if (
                    self.state.logged_in
                    and self.state.microphone_enabled
                    and self.state.voice_mode == "normal"
                ):
                    self._start_wakeword_listener()
            if failed and not self.operation_canceling:
                self.window.chat.show_activity_error("แปลงเสียงเป็นข้อความล้มเหลว")

    def rename_user(self) -> None:
        dialog = FormDialog(
            "แก้ไขข้อมูลผู้ใช้",
            [("ชื่อผู้ใช้ (ภาษาอังกฤษและตัวเลข)", False), ("ชื่อเล่น", False)],
            self.window,
        )
        dialog.inputs[0].setText(self.state.current_username)
        dialog.inputs[1].setText(self.state.current_nickname)

        def submit(values):
            try:
                user = self.database.update_user(
                    self.state.current_user_id,
                    values[0],
                    values[1],
                )
            except ValueError as error:
                dialog.show_error(str(error))
                return
            self.state.current_username = user.username
            self.state.current_nickname = user.nickname
            self.window.chat.set_nickname(user.nickname)
            dialog.accept()

        dialog.submitted.connect(submit)
        dialog.exec()

    def change_password(self) -> None:
        dialog = FormDialog(
            "เปลี่ยนรหัสผ่าน",
            [("รหัสผ่านปัจจุบัน", True), ("รหัสผ่านใหม่", True), ("ยืนยันรหัสผ่านใหม่", True)],
            self.window,
        )

        def submit(values):
            if values[1] != values[2]:
                dialog.show_error("รหัสผ่านใหม่ไม่ตรงกัน")
                return
            try:
                self.database.change_password(self.state.current_user_id, values[0], values[1])
            except ValueError as error:
                dialog.show_error(str(error))
                return
            dialog.accept()

        dialog.submitted.connect(submit)
        dialog.exec()

    def manage_face(self) -> None:
        if not self.state.camera_enabled:
            self._show_error("กรุณาเปิดกล้องก่อนจัดการใบหน้า")
            return
        self.registration_embeddings = []
        dialog = FaceScanDialog(self.window)
        self.registration_dialog = dialog

        def save():
            try:
                self.database.replace_face_profiles(
                    self.state.current_user_id,
                    list(self.registration_embeddings),
                )
            except ValueError as error:
                self._show_error(str(error))
                return
            dialog.accept()

        dialog.next_requested.connect(save)

        def retry():
            self.registration_embeddings.clear()
            dialog.reset_scan()
            self.registration_timer.start()

        dialog.retry_requested.connect(retry)
        dialog.finished.connect(self._registration_closed)
        self.registration_timer.start()
        dialog.open()

    def _on_toggle_requested(self, key: str, enabled: bool) -> None:
        asyncio.create_task(self.set_device_enabled(key, enabled))

    async def set_device_enabled(self, key: str, enabled: bool) -> None:
        user_id = self.state.current_user_id
        if user_id is None:
            return
        if not enabled:
            if key == "camera":
                self.preview_timer.stop()
                self.login_timer.stop()
                await asyncio.to_thread(self.face.close_camera)
                self.state.camera_enabled = False
            elif key == "microphone":
                self.push_to_talk_held = False
                self.push_to_talk_recording = False
                self.resume_voice_listener_after_push = False
                self.resume_wakeword_after_push = False
                if self.manual_recorder.recording:
                    await asyncio.to_thread(self.manual_recorder.stop)
                    self.window.chat.set_manual_recording(False)
                if self.voice_listener is not None:
                    await asyncio.to_thread(self.voice_listener.stop)
                if self.wakeword_listener is not None:
                    await asyncio.to_thread(self.wakeword_listener.stop)
                self.state.microphone_enabled = False
                self.window.chat.set_mic_enabled(False)
            elif key == "tts":
                await self.audio_queue.cancel()
                self.state.tts_enabled = False
            await asyncio.to_thread(
                self.database.update_device_setting,
                user_id,
                key,
                False,
            )
            self._refresh_settings()
            return

        dialog = LoadingDialog("กำลังเตรียมระบบ", "กำลังตรวจสอบอุปกรณ์...", self.window)
        dialog.show()
        error_message: str | None = None
        try:
            if key == "camera":
                available = await asyncio.to_thread(HardwareManager.camera_available)
                if not available:
                    raise RuntimeError("ไม่พบกล้อง")
                dialog.update_message("กำลังโหลดระบบจดจำใบหน้า...")
                await asyncio.to_thread(self.face.load)
                await asyncio.to_thread(self.face.open_camera)
                self.state.camera_available = True
                self.state.camera_enabled = True
                self.preview_timer.start()
            elif key == "microphone":
                available = await asyncio.to_thread(HardwareManager.microphone_available)
                if not available:
                    raise RuntimeError("ไม่พบไมโครโฟน")
                dialog.update_message("กำลังเริ่มระบบแปลงเสียงและโหลดโมเดล...")
                await asyncio.to_thread(self.stt.start)
                if not self.wakeword_ready:
                    dialog.update_message("กำลังโหลดระบบคำปลุก Alexa...")
                    await asyncio.to_thread(self.wakeword.start)
                    self.wakeword_ready = True
                dialog.update_message("กำลังเตรียมระบบรับเสียงให้พร้อม...")
                self.state.microphone_available = True
                self.state.microphone_enabled = True
                if self.state.voice_mode == "automatic":
                    self._start_voice_listener()
                else:
                    self._start_wakeword_listener()
                self.window.chat.set_mic_enabled(True)
            elif key == "tts":
                available = await asyncio.to_thread(HardwareManager.speaker_available)
                if not available:
                    raise RuntimeError("ไม่พบลำโพงหรือหูฟัง")
                dialog.update_message("กำลังเชื่อมต่อระบบเสียงพูด...")
                await self.audio_queue.start()
                self.state.speaker_available = True
                self.state.tts_enabled = True
        except Exception as error:
            error_message = str(error)
        finally:
            if error_message is None:
                await asyncio.to_thread(
                    self.database.update_device_setting,
                    user_id,
                    key,
                    True,
                )
                await asyncio.sleep(1)
            dialog.close()
            self._refresh_settings()
        if error_message:
            self._show_error(error_message)

    def _on_test_requested(self, key: str) -> None:
        if key == "camera":
            QMessageBox.information(self.window, "ทดสอบกล้อง", "กล้องกำลังแสดงภาพและทำงานปกติครับ")
        elif key == "microphone":
            QMessageBox.information(self.window, "ทดสอบไมโครโฟน", "ไมโครโฟนพร้อมรับเสียงครับ")
        elif key == "tts" and self.state.tts_enabled:
            self.audio_queue.enqueue("ระบบเสียงทำงานปกติครับ")

    def _refresh_settings(self) -> None:
        self.window.chat.update_device(
            "camera", self.state.camera_available, self.state.camera_enabled,
        )
        self.window.chat.update_device(
            "microphone", self.state.microphone_available, self.state.microphone_enabled,
        )
        self.window.chat.update_device(
            "tts", self.state.speaker_available, self.state.tts_enabled,
        )

    def _show_error(self, message: str) -> None:
        print(f"ERROR: {message}")
        if self.state.logged_in:
            self._show_notice("เกิดข้อผิดพลาด", message, error=True)
        else:
            self.window.login.status.setText(message)

    def _on_voice_error(self, message: str) -> None:
        if not HardwareManager.microphone_available():
            print(f"MICROPHONE DISABLED: {message}")
            self.state.microphone_available = False
            self.state.microphone_enabled = False
            self.window.chat.set_mic_enabled(False)
            self._refresh_settings()
            return
        self._show_error(message)

    def _show_notice(self, title: str, message: str, error: bool = False) -> None:
        dialog = NoticeDialog(title, message, self.window, error=error)
        dialog.exec()
