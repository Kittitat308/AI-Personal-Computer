from app.application_support import *


class ChatMixin:
    async def _enter_chat_session(self) -> None:
        async with self.session_lock:
            if not self.state.logged_in or self.shutdown_started:
                return
            dialog = LoadingDialog("กำลังเตรียมระบบ", "กำลังเริ่มเซสชัน AI ใหม่...", self.window)
            dialog.show()
            errors: list[str] = []
            user_id = self.state.current_user_id
            self.ai_model_unselected = False
            try:
                await self.controller.set_active_user(user_id)
            except Exception as error:
                errors.append(f"เตรียมข้อมูลผู้ใช้ไม่สำเร็จ: {error}")
            try:
                ai_settings = await asyncio.to_thread(
                    self.database.get_ai_settings,
                    user_id,
                )
                api_key = await asyncio.to_thread(
                    self.database.get_api_key,
                    user_id,
                    "gemini",
                )
                model = self._model_for_provider(ai_settings, ai_settings.provider)
                try:
                    await self.controller.configure_provider(
                        ai_settings.provider,
                        model,
                        ai_settings.model_effort,
                        api_key,
                    )
                except Exception:
                    self.ai_model_unselected = True
                    self.window.chat.set_ai_unselected()
                    self._load_ai_settings_page(ai_settings, api_key)
                    raise
                self.ai_model_unselected = False
                self.window.chat.set_ai_models(
                    ai_settings,
                    ai_settings.provider,
                )
                self._load_ai_settings_page(ai_settings, api_key)
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

                if settings.microphone_enabled and self.state.microphone_available:
                    dialog.update_message("กำลังโหลดระบบรับเสียง...")
                    errors.extend(await self._load_microphone_services())
                    self.state.microphone_enabled = self.stt_ready
                else:
                    await self._close_microphone_services()
                    self.state.microphone_enabled = False

                if settings.tts_enabled and self.state.speaker_available:
                    dialog.update_message("กำลังเตรียมระบบเสียงพูด...")
                    errors.extend(await self._load_tts_service())
                    self.state.tts_enabled = self.tts_ready
                else:
                    await self._close_tts_service()
                    self.state.tts_enabled = False
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
                await self._close_microphone_services()
                await self._close_tts_service()
                await self.controller.reset_conversation(start=False)
                await self.controller.set_active_user(None)
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
                self.window.chat.set_model_locked(False)

    def _on_typed_message(self, text: str, attachments: list[str]) -> None:
        if self.current_operation is not None and not self.current_operation.done():
            return
        self.current_operation = asyncio.create_task(
            self.process_message(text, attachments=attachments)
        )
        self.current_operation.add_done_callback(self._operation_finished)

    @staticmethod
    def _model_for_provider(settings, provider: str) -> str:
        return {
            "qwen": settings.qwen_model,
            "gemini": settings.gemini_model,
            "claude": settings.claude_model,
        }[provider]

    def _load_ai_settings_page(self, settings, api_key: str) -> None:
        self.window.settings.load_values(
            {
                "qwen_model": settings.qwen_model,
                "gemini_model": settings.gemini_model,
                "claude_model": settings.claude_model,
                "gemini_api_key": api_key,
                "model_effort": settings.model_effort,
            }
        )

    def open_settings(self) -> None:
        if not self.state.logged_in:
            return
        settings = self.database.get_ai_settings(self.state.current_user_id)
        api_key = self.database.get_api_key(
            self.state.current_user_id,
            "gemini",
        )
        self._load_ai_settings_page(settings, api_key)
        self.window.show_settings()

    def _on_ai_provider_changed(self, provider: str) -> None:
        if not self.state.logged_in:
            return
        asyncio.create_task(self._switch_ai_provider(provider))

    def _on_model_effort_changed(self, effort: str) -> None:
        self._start_model_switch(effort=effort)

    def _on_model_changed(self, model: str) -> None:
        self._start_model_switch(model=model)

    def _start_model_switch(
        self,
        model: str | None = None,
        effort: str | None = None,
    ) -> None:
        if (
            not self.state.logged_in
            or self.ai_model_unselected
            or self.controller.provider_name not in ("gemini", "claude")
        ):
            return
        asyncio.create_task(self._switch_model_selection(model, effort))

    async def _switch_model_selection(
        self,
        model: str | None,
        effort: str | None,
    ) -> None:
        user_id = self.state.current_user_id
        if user_id is None:
            return
        provider = self.controller.provider_name
        try:
            settings = await asyncio.to_thread(
                self.database.get_ai_settings,
                user_id,
            )
            current_model = self._model_for_provider(settings, provider)
            new_model = model or current_model
            new_effort = effort or settings.model_effort
            if new_model == current_model and new_effort == settings.model_effort:
                return
            api_key = await asyncio.to_thread(
                self.database.get_api_key,
                user_id,
                "gemini",
            )
            await self.controller.configure_provider(
                provider,
                new_model,
                new_effort,
                api_key,
            )
            await asyncio.to_thread(
                self.database.update_ai_settings,
                user_id,
                provider=provider,
                qwen_model=settings.qwen_model,
                gemini_model=new_model if provider == "gemini" else settings.gemini_model,
                claude_model=new_model if provider == "claude" else settings.claude_model,
                model_effort=new_effort,
            )
            updated = await asyncio.to_thread(
                self.database.get_ai_settings,
                user_id,
            )
            self.window.chat.set_ai_models(updated, provider)
            self.window.chat.clear_messages(keep_input=True)
        except Exception as error:
            settings = await asyncio.to_thread(
                self.database.get_ai_settings,
                user_id,
            )
            self.window.chat.set_ai_models(settings, self.controller.provider_name)
            self._show_error(f"เปลี่ยนโมเดลไม่สำเร็จ: {error}")

    async def _switch_ai_provider(self, provider: str) -> None:
        user_id = self.state.current_user_id
        if user_id is None or (
            provider == self.controller.provider_name
            and not self.ai_model_unselected
        ):
            return
        dialog = LoadingDialog(
            "กำลังเปลี่ยน AI",
            "กำลังโหลดโมเดลและเริ่มเซสชันใหม่...",
            self.window,
        )
        dialog.show()
        try:
            settings = await asyncio.to_thread(
                self.database.get_ai_settings,
                user_id,
            )
            api_key = await asyncio.to_thread(
                self.database.get_api_key,
                user_id,
                "gemini",
            )
            await self.controller.configure_provider(
                provider,
                self._model_for_provider(settings, provider),
                settings.model_effort,
                api_key,
            )
            await asyncio.to_thread(
                self.database.update_ai_settings,
                user_id,
                provider=provider,
                qwen_model=settings.qwen_model,
                gemini_model=settings.gemini_model,
                claude_model=settings.claude_model,
                model_effort=settings.model_effort,
            )
            updated = await asyncio.to_thread(
                self.database.get_ai_settings,
                user_id,
            )
            self.ai_model_unselected = False
            self.window.chat.set_ai_models(updated, provider)
            self.window.chat.clear_messages(keep_input=True)
        except Exception as error:
            if self.ai_model_unselected:
                self.window.chat.set_ai_unselected()
            else:
                self.window.chat.set_ai_provider(self.controller.provider_name)
            self._show_error(f"เปลี่ยน AI ไม่สำเร็จ: {error}")
        finally:
            dialog.close()

    def _save_ai_settings(self, values: dict) -> None:
        if not self.state.logged_in:
            return
        asyncio.create_task(self._save_ai_settings_async(values))

    async def _save_ai_settings_async(self, values: dict) -> None:
        user_id = self.state.current_user_id
        if user_id is None:
            return
        try:
            await asyncio.to_thread(
                self.database.set_api_key,
                user_id,
                "gemini",
                values["gemini_api_key"],
            )
            settings = await asyncio.to_thread(
                self.database.get_ai_settings,
                user_id,
            )
            if self.controller.provider_name == "gemini":
                await self.controller.configure_provider(
                    "gemini",
                    settings.gemini_model,
                    settings.model_effort,
                    values["gemini_api_key"],
                )
            if not self.ai_model_unselected:
                self.window.chat.set_ai_models(
                    settings, self.controller.provider_name
                )
            self.window.show_chat()
        except Exception as error:
            self._show_error(f"บันทึกการตั้งค่า AI ไม่สำเร็จ: {error}")

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
        if self.ai_model_unselected:
            self._show_error("กรุณาเลือกโมเดลก่อนใช้งาน")
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
            self._sync_model_lock()

    def _sync_model_lock(self) -> None:
        # A worker waiting for the user's answer keeps the model selectors
        # locked until that task finishes or is cancelled.
        self.window.chat.set_model_locked(self.controller.awaiting_user_input)

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
                "settings": self.open_settings,
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
        cancellations = [self.controller.cancel_pending_task()]
        if self.tts_ready:
            cancellations.append(self.audio_queue.cancel())
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
            self._sync_model_lock()
            if (
                self.resume_voice_listener_after_push
                and self.state.voice_mode == "automatic"
                and self.state.microphone_enabled
            ):
                self._start_voice_listener()
            self.resume_voice_listener_after_push = False
            if was_transcribing:
                self.window.chat.show_activity_error("แปลงเสียงเป็นข้อความล้มเหลว")
