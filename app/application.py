import asyncio
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.database import Database
from app.face import FaceService
from app.gui_controller import GUIController
from app.hardware import HardwareManager
from app.state import RuntimeState
from app.stt_adapter import GUISTTService
from app.ui import FaceScanDialog, FormDialog, LoadingDialog, MainWindow, numpy_to_pixmap
from app.voice import VoiceListener
from speech.tts import AudioQueue


class ThreadBridge(QObject):
    utterance = Signal(object)
    voice_error = Signal(str)


class DesktopApplication:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.state = RuntimeState()
        self.database = Database(project_root / "data" / "ai_personal_computer.db")
        self.face = FaceService(self.database)
        self.controller = GUIController()
        self.stt = GUISTTService()
        self.audio_queue = AudioQueue()
        self.window = MainWindow()
        self.bridge = ThreadBridge()
        self.voice_listener: VoiceListener | None = None
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
        self.login_camera_starting = False
        self.account_dialog_open = False
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
        self.bridge.voice_error.connect(self._show_error)
        self.window.login.sign_in_requested.connect(self.open_sign_in)
        self.window.login.register_requested.connect(self.open_registration_without_face)
        self.window.close_requested.connect(self._request_shutdown)
        self.window.chat.message_submitted.connect(self._on_typed_message)
        self.window.chat.folder_requested.connect(self.select_folder)
        self.window.chat.settings_requested.connect(self.window.show_settings)
        self.window.chat.profile_requested.connect(self.open_profile_menu)
        self.window.settings.back_requested.connect(self.window.show_chat)
        self.window.settings.toggle_requested.connect(self._on_toggle_requested)
        self.window.settings.test_requested.connect(self._on_test_requested)

    async def start(self) -> None:
        await self.controller.start()
        camera, microphone, speaker = await asyncio.gather(
            asyncio.to_thread(HardwareManager.camera_available),
            asyncio.to_thread(HardwareManager.microphone_available),
            asyncio.to_thread(HardwareManager.speaker_available),
        )
        self.state.camera_available = camera
        self.state.microphone_available = microphone
        self.state.speaker_available = speaker

        if camera:
            try:
                await asyncio.to_thread(self.face.load)
            except Exception as error:
                self.state.camera_available = False
                self.startup_errors.append(str(error))

        if microphone:
            try:
                await asyncio.to_thread(self.stt.start)
                self.state.microphone_enabled = True
                self._start_voice_listener()
            except Exception as error:
                self.startup_errors.append(f"เปิดระบบรับเสียงไม่สำเร็จ: {error}")

        if speaker:
            try:
                await self.audio_queue.start()
                self.state.tts_enabled = True
            except Exception as error:
                self.startup_errors.append(f"เปิดระบบเสียงพูดไม่สำเร็จ: {error}")

        self._refresh_settings()
        self.window.chat.set_mic_enabled(self.state.microphone_enabled)
        self.presence_timer.start()
        if self.state.camera_available:
            self.window.login.camera.setText("กำลังเปิดกล้อง...")
        self.window.showMaximized()

        # Let Qt present the Login page before opening the physical camera.
        await asyncio.sleep(0.05)
        if self.state.camera_available and not self.shutdown_started:
            try:
                await asyncio.to_thread(self.face.open_camera)
                self.state.camera_enabled = True
                self.preview_timer.start()
                self.login_timer.start()
            except Exception as error:
                self.state.camera_available = False
                self.window.login.camera.setText("ไม่พบกล้อง")
                self.startup_errors.append(str(error))
        self._refresh_settings()
        if self.startup_errors:
            QTimer.singleShot(
                0,
                lambda: self._show_error("\n".join(self.startup_errors)),
            )

    async def close(self) -> None:
        if self.closed:
            return
        self.preview_timer.stop()
        self.login_timer.stop()
        self.presence_timer.stop()
        self.registration_timer.stop()
        self.recovery_timer.stop()
        errors: list[str] = []
        if self.voice_listener is not None:
            try:
                await asyncio.to_thread(self.voice_listener.stop)
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
                    and not self.state.assistant_busy
                ),
                on_error=lambda error: self.bridge.voice_error.emit(str(error)),
            )
        self.voice_listener.start()

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
            result = await asyncio.to_thread(self.face.extract_largest, frame)
            if not result.detected:
                self.registration_embeddings.clear()
                if self.registration_dialog is not None:
                    self.registration_dialog.status.setText("มองกล้องเพื่อสแกนใบหน้า")
                return
            self.registration_embeddings.append(result.embedding)
            if len(self.registration_embeddings) >= 3 and self.registration_dialog is not None:
                self.registration_timer.stop()
                self.registration_dialog.set_complete()
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
            if values[2] != values[3]:
                dialog.show_error("รหัสผ่านไม่ตรงกัน")
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
        if not should_restore or self.shutdown_started or not self.state.camera_available:
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
        self.login_face_count = 0
        self.presence_missing_count = 0
        self.window.show_chat()

    def logout(self) -> None:
        self.state.logout()
        self.controller.set_allowed_directory(None)
        self.presence_missing_count = 0
        self.window.show_login()
        self.window.login.status.setText("มองกล้องเพื่อเข้าสู่ระบบ")
        asyncio.create_task(self._prepare_login_camera())

    async def _prepare_login_camera(self) -> None:
        if self.login_camera_starting or self.shutdown_started:
            return
        if self.state.camera_enabled:
            self.preview_timer.start()
            self.login_timer.start()
            return

        self.login_camera_starting = True
        self.window.login.camera.setText("กำลังเปิดกล้อง...")
        try:
            available = await asyncio.to_thread(HardwareManager.camera_available)
            if self.shutdown_started:
                return
            self.state.camera_available = available
            if not available:
                self.window.login.camera.setText("ไม่พบกล้อง")
                self.window.login.status.setText("ลงชื่อเข้าใช้ด้วยชื่อผู้ใช้และรหัสผ่าน")
                return
            await asyncio.to_thread(self.face.load)
            await asyncio.to_thread(self.face.open_camera)
            self.state.camera_enabled = True
            self.preview_timer.start()
            self.login_timer.start()
            self.window.login.status.setText("มองกล้องเพื่อเข้าสู่ระบบ")
        except Exception as error:
            self.state.camera_available = False
            self.state.camera_enabled = False
            self.window.login.camera.setText("ไม่พบกล้อง")
            self._show_error(f"เปิดกล้องหน้าเข้าสู่ระบบไม่สำเร็จ: {error}")
        finally:
            self.login_camera_starting = False
            self._refresh_settings()

    def _on_typed_message(self, text: str) -> None:
        asyncio.create_task(self.process_message(text))

    def _on_utterance(self, audio) -> None:
        if self.state.assistant_busy or not self.state.logged_in:
            return
        self.state.assistant_busy = True
        self.window.chat.set_busy(True)
        asyncio.create_task(self._transcribe_and_process(audio))

    async def _transcribe_and_process(self, audio) -> None:
        try:
            text = (await asyncio.to_thread(self.stt.transcribe_audio, audio)).strip()
            if not text:
                return
            if self.stt.is_shutdown_command(text):
                self.window.close()
                return
            await self.process_message(text, busy_already=True)
        except Exception as error:
            self._show_error(f"แปลงเสียงไม่สำเร็จ: {error}")
        finally:
            if self.state.assistant_busy:
                self.state.assistant_busy = False
                self.window.chat.set_busy(False)

    async def process_message(self, text: str, busy_already: bool = False) -> None:
        if self.state.assistant_busy and not busy_already:
            return
        self.state.assistant_busy = True
        self.window.chat.set_busy(True)
        self.window.chat.add_message(text, "user")
        try:
            if self.controller.awaiting_user_input:
                worker = await self.controller.continue_task(text)
                self.window.chat.add_message(worker.response, "result")
                self._speak(worker.response)
            else:
                chat = await self.controller.generate_chat(text)
                self.window.chat.add_message(chat.response, "assistant")
                self._speak(chat.response)
                worker = await self.controller.execute_task(chat)
                if worker is not None:
                    self.window.chat.add_message(worker.response, "result")
                    self._speak(worker.response)
            await self.controller.rotate_chat_if_ready()
            if self.state.tts_enabled:
                await self.audio_queue.wait_until_idle()
        except Exception as error:
            self.window.chat.add_message(f"เกิดข้อผิดพลาด: {error}", "result")
        finally:
            self.state.assistant_busy = False
            self.window.chat.set_busy(False)

    def _speak(self, text: str) -> None:
        if self.state.tts_enabled:
            self.audio_queue.enqueue(text)

    def select_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self.window, "เลือกโฟลเดอร์")
        if path:
            self.state.allowed_folder = path
            self.controller.set_allowed_directory(path)
            self.window.chat.add_message(f"อนุญาตให้เข้าถึงโฟลเดอร์ {path} แล้วครับ", "result")

    def open_profile_menu(self, anchor) -> None:
        self.window.show_profile_menu(
            anchor,
            f"{self.state.current_nickname}  (@{self.state.current_username})",
            {
                "rename": self.rename_user,
                "face": self.manage_face,
                "password": self.change_password,
                "logout": self.logout,
            },
        )

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
        dialog.finished.connect(self._registration_closed)
        self.registration_timer.start()
        dialog.open()

    def _on_toggle_requested(self, key: str, enabled: bool) -> None:
        asyncio.create_task(self.set_device_enabled(key, enabled))

    async def set_device_enabled(self, key: str, enabled: bool) -> None:
        if not enabled:
            if key == "camera":
                self.preview_timer.stop()
                self.login_timer.stop()
                await asyncio.to_thread(self.face.close_camera)
                self.state.camera_enabled = False
            elif key == "microphone":
                if self.voice_listener is not None:
                    await asyncio.to_thread(self.voice_listener.stop)
                await asyncio.to_thread(self.stt.close)
                self.state.microphone_enabled = False
                self.window.chat.set_mic_enabled(False)
            elif key == "tts":
                await self.audio_queue.close()
                self.state.tts_enabled = False
            self._refresh_settings()
            return

        dialog = LoadingDialog("กำลังเตรียมระบบ", "กำลังตรวจสอบอุปกรณ์...", self.window)
        dialog.show()
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
                self.login_timer.start()
            elif key == "microphone":
                available = await asyncio.to_thread(HardwareManager.microphone_available)
                if not available:
                    raise RuntimeError("ไม่พบไมโครโฟน")
                dialog.update_message("กำลังเริ่มระบบแปลงเสียงและโหลดโมเดล...")
                await asyncio.to_thread(self.stt.start)
                dialog.update_message("กำลังเตรียมระบบรับเสียงให้พร้อม...")
                self.state.microphone_available = True
                self.state.microphone_enabled = True
                self._start_voice_listener()
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
            self._show_error(str(error))
        finally:
            dialog.close()
            self._refresh_settings()

    def _on_test_requested(self, key: str) -> None:
        if key == "camera":
            QMessageBox.information(self.window, "ทดสอบกล้อง", "กล้องกำลังแสดงภาพและทำงานปกติครับ")
        elif key == "microphone":
            QMessageBox.information(self.window, "ทดสอบไมโครโฟน", "ไมโครโฟนพร้อมรับเสียงครับ")
        elif key == "tts" and self.state.tts_enabled:
            self.audio_queue.enqueue("ระบบเสียงทำงานปกติครับ")

    def _refresh_settings(self) -> None:
        self.window.settings.update_device(
            "camera", self.state.camera_available, self.state.camera_enabled,
            "ตรวจพบกล้อง" if self.state.camera_available else "ไม่พบกล้อง",
        )
        self.window.settings.update_device(
            "microphone", self.state.microphone_available, self.state.microphone_enabled,
            "ตรวจพบไมโครโฟน" if self.state.microphone_available else "ไม่พบไมโครโฟน",
        )
        self.window.settings.update_device(
            "tts", self.state.speaker_available, self.state.tts_enabled,
            "ตรวจพบลำโพงหรือหูฟัง" if self.state.speaker_available else "ไม่พบลำโพงหรือหูฟัง",
        )

    def _show_error(self, message: str) -> None:
        print(f"ERROR: {message}")
        if self.state.logged_in:
            self.window.chat.add_message(message, "result")
        else:
            self.window.login.status.setText(message)
