from app.application_support import *


class LifecycleMixin:
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

        # Only face recognition is loaded before Login appears. Speech services
        # are loaded after a user signs in and their saved settings are known.
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

        return errors

    async def _load_microphone_services(self) -> list[str]:
        errors: list[str] = []
        if not self.state.microphone_available:
            return errors
        if not self.stt_ready:
            try:
                await asyncio.to_thread(self.stt.start)
                self.stt_ready = True
            except Exception as error:
                errors.append(f"โหลดระบบรับเสียงไม่สำเร็จ: {error}")
                return errors
        if not self.wakeword_ready:
            try:
                await asyncio.to_thread(self.wakeword.start)
                self.wakeword_ready = True
            except Exception as error:
                errors.append(f"โหลดระบบคำปลุก Alexa ไม่สำเร็จ: {error}")
        return errors

    async def _close_microphone_services(self) -> None:
        if self.voice_listener is not None:
            await asyncio.to_thread(self.voice_listener.stop)
        if self.wakeword_listener is not None:
            await asyncio.to_thread(self.wakeword_listener.stop)
        await asyncio.to_thread(self.manual_recorder.close)
        await asyncio.to_thread(self.wakeword.close)
        await asyncio.to_thread(self.stt.close)
        self.stt_ready = False
        self.wakeword_ready = False

    async def _load_tts_service(self) -> list[str]:
        if not self.state.speaker_available or self.tts_ready:
            return []
        try:
            await self.audio_queue.start()
            self.tts_ready = True
            return []
        except Exception as error:
            return [f"เตรียมระบบเสียงพูดไม่สำเร็จ: {error}"]

    async def _close_tts_service(self) -> None:
        if not self.tts_ready:
            return
        await self.audio_queue.cancel()
        await self.audio_queue.close()
        self.tts_ready = False

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
            self.wakeword_ready = False
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
            self.stt_ready = False
        except Exception as error:
            errors.append(str(error))
        try:
            await self.audio_queue.close()
            self.tts_ready = False
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
            if frame is None:
                return
            result = await asyncio.to_thread(self.face.extract_largest, frame)
            user = None
            if result.detected:
                user = await asyncio.to_thread(self.face.recognize, result.embedding)
            if user is not None and user.id == self.state.current_user_id:
                self.presence_missing_count = 0
                return
            # No face, or a face that is not the signed-in user, both mean the
            # current user was not found in this check.
            self.presence_missing_count += 1
            if self.presence_missing_count >= 3:
                self.logout()
        except Exception:
            # Camera and recognition errors are not evidence that the user left.
            return
        finally:
            self.presence_check_running = False
