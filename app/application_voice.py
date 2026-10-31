from app.application_support import *


class VoiceDeviceMixin:
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
        self.state.voice_mode = mode
        self.window.chat.set_voice_mode(mode)
        if mode == "automatic" and self.state.microphone_enabled:
            self._start_voice_listener()

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
            return
        self.state.assistant_busy = True
        self.stt_in_progress = True
        self.window.chat.set_busy(True, "กำลังแปลงเสียงเป็นข้อความ")
        self.stt.prepare_transcription()
        self.current_operation = asyncio.create_task(self._transcribe_to_input(audio))
        self.current_operation.add_done_callback(self._operation_finished)

    async def _start_manual_recording(self) -> None:
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
        if self.resume_voice_listener_after_push:
            await asyncio.to_thread(self.voice_listener.stop)
        if not self.push_to_talk_held:
            if self.resume_voice_listener_after_push:
                self._start_voice_listener()
            self.resume_voice_listener_after_push = False
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
                self.resume_voice_listener_after_push = False
        except Exception as error:
            self.push_to_talk_recording = False
            self.window.chat.set_manual_recording(False)
            if self.resume_voice_listener_after_push:
                self._start_voice_listener()
            self.resume_voice_listener_after_push = False
            self._show_error(f"เปิดไมโครโฟนไม่สำเร็จ: {error}")

    async def _finish_push_to_talk(self) -> None:
        if not self.push_to_talk_recording:
            return
        self.push_to_talk_recording = False
        resume_voice_listener = self.resume_voice_listener_after_push
        self.resume_voice_listener_after_push = False
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
            if failed and not self.operation_canceling:
                self.window.chat.show_activity_error("แปลงเสียงเป็นข้อความล้มเหลว")

    def rename_user(self) -> None:
        dialog = FormDialog(
            "แก้ไขข้อมูลผู้ใช้",
            [
                ("ชื่อผู้ใช้ (อังกฤษตัวเล็กและตัวเลข)", False, True, "ชื่อผู้ใช้"),
                ("ชื่อเล่น", False, True, "ชื่อเล่น"),
                ("Gmail สำหรับกู้คืน (ถ้ามี)", False, False, "Gmail สำหรับกู้คืน"),
            ],
            self.window,
            compact_actions=True,
            field_actions={2: "ยืนยัน"},
            submit_text="บันทึก",
        )
        dialog.inputs[0].setText(self.state.current_username)
        dialog.inputs[1].setText(self.state.current_nickname)
        recovery_gmail, recovery_gmail_verified = (
            self.database.get_recovery_gmail_status(self.state.current_user_id)
        )
        dialog.inputs[2].setText(recovery_gmail)
        dialog.set_field_verified(2, recovery_gmail_verified, recovery_gmail)
        dialog.field_action_requested.connect(
            lambda index: self._verify_form_gmail(
                dialog,
                index,
                self.state.current_user_id,
            )
        )

        def submit(values):
            validation = self.database.validate_user_profile(
                values[0],
                values[1],
                values[2],
            )
            field_indexes = {
                "username": 0,
                "nickname": 1,
                "recovery_gmail": 2,
            }
            if validation:
                dialog.show_errors(
                    {
                        field_indexes[name]: message
                        for name, message in validation.items()
                    }
                )
                return
            try:
                user = self.database.update_user(
                    self.state.current_user_id,
                    values[0],
                    values[1],
                    values[2],
                    recovery_gmail_verified=dialog.is_field_verified(2),
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
            [
                ("รหัสผ่านปัจจุบัน", True),
                ("รหัสผ่านใหม่", True),
                ("ยืนยันรหัสผ่านใหม่", True),
            ],
            self.window,
            secondary_text="ลืมรหัสผ่าน",
            compact_secondary_actions=True,
        )
        forgot_password = False

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

        def request_password_recovery() -> None:
            nonlocal forgot_password
            forgot_password = True
            dialog.reject()

        dialog.secondary_requested.connect(request_password_recovery)
        dialog.exec()
        if forgot_password:
            QTimer.singleShot(0, self._start_chat_password_recovery)

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
                if self.manual_recorder.recording:
                    await asyncio.to_thread(self.manual_recorder.stop)
                    self.window.chat.set_manual_recording(False)
                await self._close_microphone_services()
                self.state.microphone_enabled = False
                self.window.chat.set_mic_enabled(False)
            elif key == "tts":
                await self._close_tts_service()
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
                self.state.microphone_available = True
                dialog.update_message("กำลังเริ่มระบบแปลงเสียงและโหลดโมเดล...")
                service_errors = await self._load_microphone_services()
                if not self.stt_ready:
                    raise RuntimeError("\n".join(service_errors))
                dialog.update_message("กำลังเตรียมระบบรับเสียงให้พร้อม...")
                self.state.microphone_enabled = True
                if self.state.voice_mode == "automatic":
                    self._start_voice_listener()
                self.window.chat.set_mic_enabled(True)
            elif key == "tts":
                available = await asyncio.to_thread(HardwareManager.speaker_available)
                if not available:
                    raise RuntimeError("ไม่พบลำโพงหรือหูฟัง")
                self.state.speaker_available = True
                dialog.update_message("กำลังเชื่อมต่อระบบเสียงพูด...")
                service_errors = await self._load_tts_service()
                if service_errors:
                    raise RuntimeError("\n".join(service_errors))
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
            asyncio.create_task(self._close_microphone_services())
            self._refresh_settings()
            return
        self._show_error(message)

    def _show_notice(self, title: str, message: str, error: bool = False) -> None:
        dialog = NoticeDialog(title, message, self.window, error=error)
        dialog.exec()
