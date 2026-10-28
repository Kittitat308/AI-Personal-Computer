from app.application_support import *


class AccountMixin:
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
        if self.otp_dialog is not None or self.account_dialog_open:
            return
        camera_was_enabled = self._suspend_camera_for_account_dialog()
        self.account_dialog_open = True
        dialog = FormDialog(
            "ลืมรหัสผ่าน",
            [("Gmail สำหรับกู้คืน", False, True, "Gmail สำหรับกู้คืน")],
            self.window,
            submit_text="ถัดไป",
        )
        selected_user = None
        selected_gmail = ""

        def submit(values: list[str]) -> None:
            nonlocal selected_user, selected_gmail
            gmail = values[0].strip()
            error = self.database.validate_recovery_gmail(gmail)
            if error:
                dialog.show_errors({0: error})
                return
            user = self.database.get_user_by_verified_recovery_gmail(gmail)
            if user is None:
                dialog.show_errors({0: "ไม่มีเมลนี้ในระบบ"})
                return
            selected_user = user
            selected_gmail = gmail
            dialog.accept()

        dialog.submitted.connect(submit)
        try:
            dialog.exec()
        finally:
            self.account_dialog_open = False
            self._restore_camera_after_account_dialog(camera_was_enabled)
        if selected_user is not None:
            QTimer.singleShot(
                0,
                lambda user=selected_user, gmail=selected_gmail:
                self._open_otp_password_recovery(user, gmail),
            )

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
            if (
                self.recovery_target_user_id is not None
                and user.id != self.recovery_target_user_id
            ):
                if self.recovery_dialog is not None:
                    self.recovery_dialog.status.setText(
                        "ใบหน้าไม่ตรงกับบัญชีที่กำลังใช้งาน"
                    )
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
        self.recovery_target_user_id = None

    def _start_chat_password_recovery(self) -> None:
        user_id = self.state.current_user_id
        if user_id is None:
            return
        user = self.database.get_user(user_id)
        if user is None:
            self._show_error("ไม่พบบัญชีผู้ใช้")
            return
        has_face = self.database.user_has_face_profiles(user_id)
        recovery_gmail = self.database.get_verified_recovery_gmail(user_id)

        if has_face and self.state.camera_enabled:
            self._open_chat_face_recovery(user_id)
            return
        if recovery_gmail:
            self._open_otp_password_recovery(user, recovery_gmail)
            return
        if has_face:
            self._show_error("กรุณาเปิดกล้องก่อนกู้คืนรหัสผ่านด้วยใบหน้า")
            return
        self._show_error(
            "ไม่มีใบหน้าหรือ Gmail สำหรับการกู้คืนรหัสผ่าน"
        )

    def _open_chat_face_recovery(self, user_id: int) -> None:
        if self.recovery_dialog is not None or self.account_dialog_open:
            return
        self.recovery_face_count = 0
        self.recovery_target_user_id = user_id
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

    def _open_otp_password_recovery(self, user, recovery_gmail: str) -> None:
        if self.otp_dialog is not None or self.account_dialog_open:
            return
        self.account_dialog_open = True
        self._open_otp_dialog(
            recovery_gmail,
            lambda selected_user=user: self._open_reset_password_form(selected_user),
            self.window,
            controls_account_dialog=True,
        )

    def _open_otp_dialog(
        self,
        recipient: str,
        success_callback,
        parent=None,
        controls_account_dialog: bool = False,
    ) -> None:
        if self.otp_dialog is not None:
            return
        dialog = OtpDialog(self._mask_gmail(recipient), parent or self.window)
        self.otp_dialog = dialog
        self.otp_recipient = recipient
        self.otp_success_callback = success_callback
        self.otp_controls_account_dialog = controls_account_dialog
        dialog.code_completed.connect(self._verify_recovery_otp)
        dialog.resend_requested.connect(self._request_recovery_otp)
        dialog.finished.connect(self._otp_recovery_closed)
        dialog.open()
        self._request_recovery_otp()

    def _request_recovery_otp(self) -> None:
        if self.otp_dialog is None or not self.otp_recipient:
            return
        self.otp_dialog.set_sending()
        asyncio.create_task(self._send_recovery_otp())

    async def _send_recovery_otp(self) -> None:
        dialog = self.otp_dialog
        recipient = self.otp_recipient
        if dialog is None or not recipient:
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            await asyncio.to_thread(
                self.recovery_email.send_otp,
                recipient,
                code,
            )
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

    def _verify_recovery_otp(self, code: str) -> None:
        dialog = self.otp_dialog
        if dialog is None or self.otp_success_callback is None:
            return
        if time.monotonic() > self.otp_expires_at:
            dialog.reset_code("รหัสหมดอายุแล้ว กรุณาส่งรหัสอีกครั้ง")
            return
        if not self.otp_code or not hmac.compare_digest(code, self.otp_code):
            dialog.reset_code("รหัสไม่ถูกต้อง")
            return
        success_callback = self.otp_success_callback
        dialog.accept()
        QTimer.singleShot(0, success_callback)

    def _otp_recovery_closed(self) -> None:
        controls_account_dialog = self.otp_controls_account_dialog
        self.otp_dialog = None
        self.otp_recipient = ""
        self.otp_success_callback = None
        self.otp_controls_account_dialog = False
        self.otp_code = ""
        self.otp_expires_at = 0.0
        if controls_account_dialog:
            self.account_dialog_open = False

    def _verify_form_gmail(
        self,
        dialog: FormDialog,
        field_index: int,
        user_id: int | None = None,
    ) -> None:
        gmail = dialog.inputs[field_index].text().strip()
        error = self.database.validate_recovery_gmail(gmail)
        if error:
            dialog.show_errors({field_index: error})
            return
        if not gmail:
            return
        if user_id is not None:
            saved_gmail, saved_verified = (
                self.database.get_recovery_gmail_status(user_id)
            )
            if saved_verified and saved_gmail.casefold() == gmail.casefold():
                dialog.set_field_verified(field_index, True, gmail)
                return
        if self.database.recovery_gmail_in_use(gmail, user_id):
            dialog.show_errors({field_index: "Gmail นี้ถูกใช้งานไปแล้ว"})
            return
        self._open_otp_dialog(
            gmail,
            lambda selected_dialog=dialog, index=field_index, value=gmail:
            selected_dialog.set_field_verified(index, True, value),
            dialog,
        )

    @staticmethod
    def _mask_gmail(address: str) -> str:
        local, separator, domain = address.partition("@")
        if not separator:
            return address
        visible = local[:2]
        return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"

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
            lambda index: self._verify_form_gmail(dialog, index, None)
        )

        def submit(values: list[str]) -> None:
            validation = self.database.validate_new_user(
                values[0],
                values[1],
                values[2],
                values[4],
            )
            field_indexes = {
                "username": 0,
                "nickname": 1,
                "password": 2,
                "recovery_gmail": 4,
            }
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
                    recovery_gmail=values[4],
                    recovery_gmail_verified=dialog.is_field_verified(4),
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
        self.window.chat.set_permission_mode("ask")
        self.controller.set_admin_permission_mode("ask")
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

