import asyncio
import hmac
import os
import secrets
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.database import Database
from app.face import FaceService
from app.hardware import HardwareManager
from app.recovery_email import RecoveryEmailSender
from app.ui import (
    FaceScanDialog,
    FormDialog,
    MainWindow,
    NoticeDialog,
    OtpDialog,
    numpy_to_pixmap,
)
from aipc_system.auth_client import AuthClient
from aipc_system.paths import PROJECT_ROOT


SYSTEM_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
if SYSTEM_DIST_PACKAGES not in sys.path:
    sys.path.append(SYSTEM_DIST_PACKAGES)
import gi

gi.require_version("LightDM", "1")
from gi.repository import GLib, LightDM


class GreeterApplication:
    def __init__(self):
        self.window = MainWindow()
        self.window.show_login()
        self.auth = AuthClient()
        self.face = FaceService(self.auth)
        self.recovery_email = RecoveryEmailSender(PROJECT_ROOT)
        self.greeter = LightDM.Greeter()
        self.latest_frame = None
        self.face_count = 0
        self.face_check_running = False
        self.authentication_password = ""
        self.authentication_dialog = None
        self.authenticating = False
        self.unknown_face_embedding: np.ndarray | None = None
        self.registration_dialog: FaceScanDialog | None = None
        self.registration_embeddings: list[np.ndarray] = []
        self.registration_scan_running = False
        self.otp_dialog: OtpDialog | None = None
        self.otp_recipient = ""
        self.otp_code = ""
        self.otp_expires_at = 0.0
        self.otp_success_callback = None

        self.preview_timer = QTimer()
        self.preview_timer.setInterval(80)
        self.preview_timer.timeout.connect(self._update_preview)
        self.face_timer = QTimer()
        self.face_timer.setInterval(1000)
        self.face_timer.timeout.connect(self._schedule_face_check)
        self.glib_timer = QTimer()
        self.glib_timer.setInterval(10)
        self.glib_timer.timeout.connect(self._pump_glib)
        self.registration_timer = QTimer()
        self.registration_timer.setInterval(700)
        self.registration_timer.timeout.connect(self._schedule_registration_scan)

        self.window.login.sign_in_requested.connect(self.open_sign_in)
        self.window.login.register_requested.connect(
            lambda: self.open_registration([])
        )
        self.window.login.restart_requested.connect(
            lambda: self._confirm_power("reboot", "รีสตาร์ตเครื่อง")
        )
        self.window.login.shutdown_requested.connect(
            lambda: self._confirm_power("poweroff", "ปิดเครื่อง")
        )
        self.window.close_requested.connect(lambda: None)

        self.greeter.connect("show-prompt", self._on_show_prompt)
        self.greeter.connect(
            "authentication-complete",
            self._on_authentication_complete,
        )
        self.greeter.connect("show-message", self._on_show_message)

    async def start(self) -> None:
        if not self.auth.health():
            raise RuntimeError("บริการบัญชียังไม่พร้อม")
        if not self.greeter.connect_to_daemon_sync():
            raise RuntimeError("เชื่อมต่อ LightDM ไม่สำเร็จ")
        self.glib_timer.start()

        camera_available = await asyncio.to_thread(HardwareManager.camera_available)
        if camera_available:
            try:
                await asyncio.to_thread(self.face.load)
                self.window.login.camera.setText("กำลังเปิดกล้อง...")
            except Exception:
                camera_available = False

        self.window.showFullScreen()
        await asyncio.sleep(0.05)
        if camera_available:
            try:
                await asyncio.to_thread(self.face.open_camera)
                self.window.login.status.setText("มองกล้องเพื่อเข้าสู่ระบบ")
                self.preview_timer.start()
                self.face_timer.start()
            except Exception:
                camera_available = False
        if not camera_available:
            self.window.login.camera.setText("ไม่พบกล้อง")
            self.window.login.status.setText(
                "ลงชื่อเข้าใช้ด้วยชื่อผู้ใช้และรหัสผ่าน"
            )

    async def close(self) -> None:
        self.preview_timer.stop()
        self.face_timer.stop()
        self.glib_timer.stop()
        self.registration_timer.stop()
        await asyncio.to_thread(self.face.close)

    def _pump_glib(self) -> None:
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def _update_preview(self) -> None:
        frame = self.face.read_frame()
        if frame is None:
            return
        self.latest_frame = frame
        self.window.login.show_frame(
            numpy_to_pixmap(self.face.frame_to_rgb(frame))
        )
        if self.registration_dialog is not None:
            self.registration_dialog.show_frame(
                numpy_to_pixmap(self.face.frame_to_rgb(frame))
            )

    def _schedule_face_check(self) -> None:
        if (
            self.face_check_running
            or self.authenticating
            or self.latest_frame is None
        ):
            return
        self.face_check_running = True
        asyncio.create_task(self._face_check(self.latest_frame.copy()))

    async def _face_check(self, frame) -> None:
        try:
            detected = await asyncio.to_thread(self.face.has_face, frame)
            if not detected:
                self.face_count = 0
                return
            self.face_count += 1
            if self.face_count < 3:
                return
            self.face_count = 0
            result = await asyncio.to_thread(self.face.extract_largest, frame)
            if not result.detected or result.embedding is None:
                return
            user = await asyncio.to_thread(self.face.recognize, result.embedding)
            if user is None:
                self.open_face_registration()
                return
            await asyncio.to_thread(self.auth.issue_face_token, user.username)
            self._start_authentication(user.username)
        except Exception as error:
            self.window.login.status.setText(str(error))
        finally:
            self.face_check_running = False

    def _start_authentication(self, username: str, password: str = "", dialog=None) -> None:
        if self.authenticating:
            return
        self.authenticating = True
        self.authentication_password = password
        self.authentication_dialog = dialog
        self.face_timer.stop()
        self.greeter.authenticate(username)

    def _on_show_prompt(self, _greeter, _text, _prompt_type) -> None:
        self.greeter.respond(self.authentication_password)

    def _on_show_message(self, _greeter, text, _message_type) -> None:
        if text:
            self.window.login.status.setText(str(text))

    def _on_authentication_complete(self, _greeter) -> None:
        if self.greeter.get_is_authenticated():
            if self.authentication_dialog is not None:
                self.authentication_dialog.accept()
            session = self.greeter.get_default_session_hint() or "rpd-labwc"
            if not self.greeter.start_session_sync(session):
                self._authentication_failed("เปิด Desktop ไม่สำเร็จ")
            return
        self._authentication_failed("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    def _authentication_failed(self, message: str) -> None:
        if self.authentication_dialog is not None:
            self.authentication_dialog.show_error(message)
        else:
            self.window.login.status.setText(message)
        self.authentication_dialog = None
        self.authentication_password = ""
        self.authenticating = False
        self.face_count = 0
        if self.preview_timer.isActive():
            self.face_timer.start()

    def open_sign_in(self) -> None:
        self.face_timer.stop()
        dialog = FormDialog(
            "ลงชื่อเข้าใช้",
            [("ชื่อผู้ใช้", False), ("รหัสผ่าน", True)],
            self.window,
            secondary_text="ลืมรหัสผ่าน",
        )
        forgot_password = False
        dialog.submitted.connect(
            lambda values: self._start_authentication(
                values[0].strip(),
                values[1],
                dialog,
            )
        )
        def request_password_recovery() -> None:
            nonlocal forgot_password
            forgot_password = True
            dialog.reject()

        dialog.secondary_requested.connect(request_password_recovery)
        dialog.exec()
        if not self.authenticating and self.preview_timer.isActive():
            self.face_timer.start()
        if forgot_password:
            QTimer.singleShot(0, self.open_password_recovery)

    def open_face_registration(self) -> None:
        if self.registration_dialog is not None or self.authenticating:
            return
        self.face_timer.stop()
        self.registration_embeddings.clear()
        dialog = FaceScanDialog(self.window)
        self.registration_dialog = dialog

        def retry() -> None:
            self.registration_embeddings.clear()
            dialog.reset_scan()
            self.registration_timer.start()

        def confirm() -> None:
            embeddings = list(self.registration_embeddings)
            dialog.accept()
            QTimer.singleShot(0, lambda: self.open_registration(embeddings))

        dialog.retry_requested.connect(retry)
        dialog.next_requested.connect(confirm)
        dialog.finished.connect(self._registration_closed)
        self.registration_timer.start()
        dialog.open()

    def _schedule_registration_scan(self) -> None:
        if (
            self.registration_dialog is None
            or self.registration_scan_running
            or self.latest_frame is None
        ):
            return
        self.registration_scan_running = True
        asyncio.create_task(self._registration_scan(self.latest_frame.copy()))

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
            if len(self.registration_embeddings) >= 3 and self.registration_dialog:
                self.registration_timer.stop()
                self.registration_dialog.set_complete(
                    numpy_to_pixmap(self.face.frame_to_rgb(frame))
                )
        except Exception as error:
            if self.registration_dialog is not None:
                self.registration_dialog.status.setText(str(error))
        finally:
            self.registration_scan_running = False

    def _registration_closed(self) -> None:
        self.registration_timer.stop()
        self.registration_dialog = None
        self.registration_scan_running = False
        if not self.authenticating and self.preview_timer.isActive():
            self.face_timer.start()

    def open_registration(self, embeddings: list[np.ndarray]) -> None:
        if self.authenticating:
            return
        self.face_timer.stop()
        dialog = FormDialog(
            "สมัครบัญชีด้วยใบหน้า" if embeddings else "สมัครบัญชี",
            [
                ("ชื่อผู้ใช้ (อังกฤษตัวเล็กและตัวเลข)", False, True, "ชื่อผู้ใช้"),
                ("ชื่อเล่น", False, True, "ชื่อเล่น"),
                ("รหัสผ่าน", True, True, "รหัสผ่าน"),
                ("ยืนยันรหัสผ่าน", True, True, "ยืนยันรหัสผ่าน"),
                ("Gmail สำหรับกู้คืน (ถ้ามี)", False, False, "Gmail สำหรับกู้คืน"),
            ],
            self.window,
            compact_actions=True,
            field_actions={4: "ยืนยัน"},
        )

        dialog.field_action_requested.connect(
            lambda index: self._verify_form_gmail(dialog, index)
        )

        async def create(values: list[str]) -> None:
            validation = Database.validate_new_user(
                values[0], values[1], values[2], values[4]
            )
            indexes = {"username": 0, "nickname": 1, "password": 2, "recovery_gmail": 4}
            errors = {indexes[name]: text for name, text in validation.items()}
            if values[2] != values[3]:
                errors[3] = "รหัสผ่านไม่ตรงกัน"
            if errors:
                dialog.show_errors(errors)
                return
            try:
                user = await asyncio.to_thread(
                    self.auth.create_user,
                    values[0],
                    values[1],
                    values[2],
                    embeddings,
                    values[4],
                    dialog.is_field_verified(4),
                )
            except Exception as error:
                dialog.show_error(str(error))
                return
            self._start_authentication(user.username, values[2], dialog)

        dialog.submitted.connect(lambda values: asyncio.create_task(create(values)))
        dialog.exec()
        self.unknown_face_embedding = None
        if not self.authenticating and self.preview_timer.isActive():
            self.face_timer.start()

    def _verify_form_gmail(self, dialog: FormDialog, field_index: int) -> None:
        gmail = dialog.inputs[field_index].text().strip()
        error = self.auth.validate_recovery_gmail(gmail)
        if error:
            dialog.show_errors({field_index: error})
            return
        if not gmail:
            return
        try:
            in_use = self.auth.recovery_gmail_in_use_public(gmail)
        except Exception as error:
            dialog.show_errors({field_index: str(error)})
            return
        if in_use:
            dialog.show_errors({field_index: "Gmail นี้ถูกใช้งานไปแล้ว"})
            return
        self._open_otp_dialog(
            gmail,
            lambda: dialog.set_field_verified(field_index, True, gmail),
            dialog,
        )

    def open_password_recovery(self) -> None:
        dialog = FormDialog(
            "ลืมรหัสผ่าน",
            [("Gmail สำหรับกู้คืน", False, True, "Gmail สำหรับกู้คืน")],
            self.window,
            submit_text="ถัดไป",
        )
        selected = {"user": None, "gmail": ""}

        def submit(values: list[str]) -> None:
            gmail = values[0].strip()
            error = self.auth.validate_recovery_gmail(gmail)
            if error:
                dialog.show_errors({0: error})
                return
            try:
                user = self.auth.get_user_by_verified_recovery_gmail(gmail)
            except Exception as error:
                dialog.show_errors({0: str(error)})
                return
            if user is None:
                dialog.show_errors({0: "ไม่มีเมลนี้ในระบบ"})
                return
            selected["user"] = user
            selected["gmail"] = gmail
            dialog.accept()

        dialog.submitted.connect(submit)
        dialog.exec()
        user = selected["user"]
        if user is not None:
            QTimer.singleShot(
                0,
                lambda: self._open_otp_dialog(
                    selected["gmail"],
                    lambda: self._open_reset_password_form(user),
                    self.window,
                ),
            )

    def _open_otp_dialog(self, recipient: str, success_callback, parent=None) -> None:
        if self.otp_dialog is not None:
            return
        dialog = OtpDialog(self._mask_gmail(recipient), parent or self.window)
        self.otp_dialog = dialog
        self.otp_recipient = recipient
        self.otp_success_callback = success_callback
        dialog.code_completed.connect(self._verify_otp)
        dialog.resend_requested.connect(self._request_otp)
        dialog.finished.connect(self._otp_closed)
        dialog.open()
        self._request_otp()

    def _request_otp(self) -> None:
        if self.otp_dialog is None or not self.otp_recipient:
            return
        self.otp_dialog.set_sending()
        asyncio.create_task(self._send_otp())

    async def _send_otp(self) -> None:
        dialog = self.otp_dialog
        recipient = self.otp_recipient
        if dialog is None or not recipient:
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            await asyncio.to_thread(self.recovery_email.send_otp, recipient, code)
        except Exception as error:
            print(f"RECOVERY EMAIL ERROR: {error}")
            if self.otp_dialog is dialog:
                dialog.show_send_error("ส่งรหัสไม่สำเร็จ กรุณาลองอีกครั้ง")
            return
        if self.otp_dialog is not dialog:
            return
        self.otp_code = code
        self.otp_expires_at = time.monotonic() + 600
        dialog.start_resend_cooldown(60)

    def _verify_otp(self, code: str) -> None:
        dialog = self.otp_dialog
        if dialog is None or self.otp_success_callback is None:
            return
        if time.monotonic() > self.otp_expires_at:
            dialog.reset_code("รหัสหมดอายุแล้ว กรุณาส่งรหัสอีกครั้ง")
            return
        if not self.otp_code or not hmac.compare_digest(code, self.otp_code):
            dialog.reset_code("รหัสไม่ถูกต้อง")
            return
        callback = self.otp_success_callback
        dialog.accept()
        QTimer.singleShot(0, callback)

    def _otp_closed(self) -> None:
        self.otp_dialog = None
        self.otp_recipient = ""
        self.otp_code = ""
        self.otp_expires_at = 0.0
        self.otp_success_callback = None

    def _open_reset_password_form(self, user) -> None:
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
                self.auth.reset_password_for_user(user.id, values[0])
            except Exception as error:
                dialog.show_error(str(error))
                return
            dialog.accept()
            self.window.login.status.setText(
                "เปลี่ยนรหัสผ่านสำเร็จ กรุณาลงชื่อเข้าใช้"
            )

        dialog.submitted.connect(submit)
        dialog.exec()

    @staticmethod
    def _mask_gmail(address: str) -> str:
        local, separator, domain = address.partition("@")
        if not separator:
            return address
        visible = local[:2]
        return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"

    def _confirm_power(self, operation: str, label: str) -> None:
        answer = QMessageBox.question(
            self.window,
            label,
            f"ยืนยันการ{label}หรือไม่",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.auth.power(operation)
        except Exception as error:
            NoticeDialog("เกิดข้อผิดพลาด", str(error), self.window, error=True).exec()
