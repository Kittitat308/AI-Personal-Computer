from app.ui_common import *
from app.ui_dialogs import (
    FaceScanDialog,
    FormDialog,
    LoadingDialog,
    LoginPage,
    NoticeDialog,
    OtpDialog,
)


from providers.catalog import PROVIDERS


def _label_for(choices, value: str) -> str:
    return next((label for label, key in choices if key == value), value)


class ChatPage(QWidget):
    message_submitted = Signal(str, object)
    folder_requested = Signal()
    folder_cleared = Signal()
    profile_requested = Signal(object)
    toggle_requested = Signal(str, bool)
    voice_mode_changed = Signal(str)
    manual_mic_requested = Signal(bool)
    stop_requested = Signal()
    attachment_requested = Signal(str)
    permission_mode_changed = Signal(str)
    ai_provider_changed = Signal(str)
    model_effort_changed = Signal(str)
    model_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._busy = False
        self._model_locked = False
        self._provider: str | None = None
        self._ai_settings = None
        self._manual_recording = False
        self._voice_mode = "normal"
        self._permission_mode = "ask"
        self._input_attachments: dict[str, AttachmentTile] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 12)
        top = QFrame()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        title = QLabel("AI Personal Computer")
        title.setObjectName("title")
        top_layout.addWidget(title)
        top_layout.addStretch()
        outer.addWidget(top)

        center = QHBoxLayout()
        center.setSpacing(14)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(300)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 14, 14, 14)
        sidebar_layout.setSpacing(12)
        self.device_rows = {}
        for key, icon, label in (
            ("camera", "camera", "กล้อง"),
            ("microphone", "microphone", "ไมโครโฟน"),
            ("tts", "speaker", "เสียง"),
        ):
            card = QFrame()
            card.setObjectName("deviceCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 10, 12, 10)
            icon_label = QLabel()
            icon_label.setObjectName("deviceIcon")
            icon_label.setPixmap(make_icon(icon, 28).pixmap(28, 28))
            icon_label.setFixedSize(32, 32)
            icon_label.setAlignment(Qt.AlignCenter)
            name = QLabel(label)
            name.setStyleSheet("font-weight:600;")
            availability = QLabel("●")
            toggle = ToggleSwitch()
            toggle.toggled.connect(
                lambda value, item=key: self.toggle_requested.emit(item, value)
            )
            row.addWidget(icon_label)
            row.addWidget(name)
            row.addStretch()
            row.addWidget(availability)
            row.addWidget(toggle)
            sidebar_layout.addWidget(card)
            self.device_rows[key] = (availability, toggle)

        mode_card = QFrame()
        mode_card.setObjectName("deviceCard")
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(14, 12, 14, 14)
        mode_layout.addWidget(QLabel("โหมดรับเสียง"))
        mode_buttons = QHBoxLayout()
        self.auto_mode_button = QPushButton("อัตโนมัติ")
        self.normal_mode_button = QPushButton("ปกติ")
        self.auto_mode_button.setCheckable(True)
        self.normal_mode_button.setCheckable(True)
        self.auto_mode_button.setObjectName("modeButton")
        self.normal_mode_button.setObjectName("modeButton")
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.auto_mode_button)
        self.mode_group.addButton(self.normal_mode_button)
        self.normal_mode_button.setChecked(True)
        self.auto_mode_button.clicked.connect(
            lambda: self.voice_mode_changed.emit("automatic")
        )
        self.normal_mode_button.clicked.connect(
            lambda: self.voice_mode_changed.emit("normal")
        )
        mode_buttons.addWidget(self.auto_mode_button)
        mode_buttons.addWidget(self.normal_mode_button)
        mode_layout.addLayout(mode_buttons)
        sidebar_layout.addWidget(mode_card)
        sidebar_layout.addStretch()
        self.profile_button = ProfileButton("ผู้ใช้")
        self.profile_button.clicked.connect(
            lambda: self.profile_requested.emit(self.profile_button)
        )
        sidebar_layout.addWidget(self.profile_button)
        center.addWidget(sidebar)

        column = QVBoxLayout()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("panel")
        self.messages = QWidget()
        self.messages_layout = QVBoxLayout(self.messages)
        self.messages_layout.setContentsMargins(34, 26, 34, 26)
        self.messages_layout.addStretch()
        self.scroll.setWidget(self.messages)
        column.addWidget(self.scroll, 1)

        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(8)
        self.attachment_scroll = QScrollArea()
        self.attachment_scroll.setWidgetResizable(True)
        self.attachment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.attachment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.attachment_scroll.setFixedHeight(74)
        self.attachment_scroll.setVisible(False)
        self.attachment_container = QWidget()
        self.attachment_layout = QHBoxLayout(self.attachment_container)
        self.attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.attachment_layout.setSpacing(8)
        self.attachment_layout.addStretch()
        self.attachment_scroll.setWidget(self.attachment_container)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(10)
        self.folder_button = QPushButton("\u00a0\u00a0เลือกโฟลเดอร์")
        self.folder_button.setIcon(make_icon("folder", 24))
        self.folder_button.setIconSize(QSize(24, 24))
        self.folder_button.setMinimumWidth(176)
        self.folder_button.clicked.connect(self.folder_requested)
        self.permission_mode_button = PermissionModeButton("ขออนุมัติ")
        self.permission_mode_button.setToolTip("เลือกรูปแบบการอนุมัติคำสั่งของ Admin")
        self.permission_mode_button.clicked.connect(
            self._show_permission_mode_menu
        )
        self.ai_provider_button = PillMenuButton("เลือก AI")
        self.ai_provider_button.setToolTip("เลือก AI ที่ใช้กับ Chat และ Worker")
        self.ai_provider_button.clicked.connect(self._show_provider_menu)
        self.model_button = PillMenuButton("เลือกโมเดล")
        self.model_button.setToolTip("เลือกโมเดลและ Effort")
        self.model_button.clicked.connect(self._show_model_menu)
        self.model_button.setEnabled(False)
        self.remove_folder_button = QPushButton()
        self.remove_folder_button.setObjectName("removeFolder")
        self.remove_folder_button.setFixedSize(42, 42)
        self.remove_folder_button.setIcon(make_icon("close", 19, "#ff4d5b"))
        self.remove_folder_button.setIconSize(QSize(19, 19))
        self.remove_folder_button.setToolTip("ยกเลิกการอนุญาตโฟลเดอร์")
        self.remove_folder_button.setVisible(False)
        self.remove_folder_button.clicked.connect(self.folder_cleared)
        self.input = MessageInput()
        self.input.setPlaceholderText("พิมพ์ข้อความ...")
        self.input.setMinimumHeight(54)
        self.input.setMaximumHeight(110)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.submit_requested.connect(self._submit)
        self.input.attachments_added.connect(self.add_input_attachments)
        self.input.textChanged.connect(self._update_send_enabled)
        self.mic_button = QPushButton("●")
        self.mic_button.setObjectName("micButton")
        self.mic_button.setFixedWidth(68)
        self.mic_button.setIcon(make_icon("microphone", 25))
        self.mic_button.setIconSize(QSize(25, 25))
        self.mic_button.setText("")
        self.mic_button.clicked.connect(self._toggle_manual_mic)
        self.send_button = QPushButton("ส่ง")
        self.send_button.setObjectName("primary")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._primary_action)
        folder_row.addWidget(self.folder_button)
        folder_row.addWidget(self.remove_folder_button)
        folder_row.addWidget(self.permission_mode_button)
        folder_row.addStretch()
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(self.ai_provider_button)
        model_row.addWidget(self.model_button)
        model_row.addStretch()
        input_grid = QGridLayout()
        input_grid.setHorizontalSpacing(10)
        input_grid.setVerticalSpacing(8)
        input_grid.setColumnStretch(0, 1)
        input_grid.addWidget(self.input, 0, 0)
        input_grid.addWidget(self.mic_button, 0, 1)
        input_grid.addWidget(self.send_button, 0, 2)
        input_grid.addLayout(model_row, 1, 0)
        composer_layout.addWidget(self.attachment_scroll)
        composer_layout.addLayout(folder_row)
        composer_layout.addLayout(input_grid)
        self.activity_status = QLabel("")
        self.activity_status.setAlignment(Qt.AlignRight)
        self.activity_status.setObjectName("activityStatus")
        column.addWidget(self.activity_status)
        column.addWidget(composer)
        center.addLayout(column, 1)
        outer.addLayout(center, 1)

    def _primary_action(self) -> None:
        if self._busy:
            self.stop_requested.emit()
        else:
            self._submit()

    def _show_permission_mode_menu(self) -> None:
        menu = QMenu(self)
        choices = (
            ("ขออนุมัติ", "ask"),
            ("อนุมัติแทนฉัน", "auto"),
        )
        for label, mode in choices:
            action = menu.addAction(label)
            if mode == self._permission_mode:
                action.setIcon(make_menu_icon("check", "#43e78f"))
            else:
                blank_icon = QPixmap(22, 22)
                blank_icon.fill(Qt.transparent)
                action.setIcon(QIcon(blank_icon))
            action.triggered.connect(
                lambda _checked=False, selected=mode: self.set_permission_mode(
                    selected,
                    emit=True,
                )
            )
        menu.ensurePolished()
        position = self.permission_mode_button.mapToGlobal(
            self.permission_mode_button.rect().topLeft()
        )
        position.setY(position.y() - menu.sizeHint().height() - 6)
        menu.exec(position)

    def _toggle_manual_mic(self) -> None:
        if not self.mic_button.isEnabled() or self._busy:
            return
        self.manual_mic_requested.emit(not self._manual_recording)

    def _submit(self) -> None:
        text = self.input.toPlainText().strip()
        attachments = list(self._input_attachments)
        if text or attachments:
            self.input.clear()
            self.clear_input_attachments()
            self.message_submitted.emit(text, attachments)

    def _update_send_enabled(self) -> None:
        if not self._busy:
            self.send_button.setEnabled(
                self.input.isEnabled()
                and bool(self.input.toPlainText().strip() or self._input_attachments)
            )

    def add_input_attachments(self, paths: list[str]) -> None:
        for raw_path in paths:
            path = Path(raw_path).resolve()
            key = str(path)
            if not path.is_file() or key in self._input_attachments:
                continue
            tile = AttachmentTile(path)
            tile.removed.connect(self.remove_input_attachment)
            self._input_attachments[key] = tile
            self.attachment_layout.insertWidget(
                self.attachment_layout.count() - 1,
                tile,
            )
        self.attachment_scroll.setVisible(bool(self._input_attachments))
        self._update_send_enabled()

    def remove_input_attachment(self, path: str) -> None:
        tile = self._input_attachments.pop(path, None)
        if tile is not None:
            tile.deleteLater()
        self.attachment_scroll.setVisible(bool(self._input_attachments))
        self._update_send_enabled()

    def clear_input_attachments(self) -> None:
        tiles = list(self._input_attachments.values())
        self._input_attachments.clear()
        for tile in tiles:
            tile.deleteLater()
        self.attachment_scroll.setVisible(False)
        self._update_send_enabled()

    def append_transcript(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        current = self.input.toPlainText()
        separator = " " if current and not current[-1].isspace() else ""
        self.input.setPlainText(current + separator + cleaned)
        cursor = self.input.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.input.setTextCursor(cursor)
        self.input.setFocus()

    def add_message(self, text: str, role: str) -> None:
        row = QHBoxLayout()
        message = QWidget()
        message_layout = QVBoxLayout(message)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(4)
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(620)
        bubble.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        bubble.setCursor(Qt.IBeamCursor)
        footer = self._message_footer(text)
        if role == "user":
            bubble.setStyleSheet("background:#075bb5;border:1px solid #1597ff;border-radius:18px;padding:14px 18px;font-size:14px;")
            message_layout.addWidget(bubble, alignment=Qt.AlignRight)
            message_layout.addWidget(footer, alignment=Qt.AlignRight)
            row.addStretch()
            row.addWidget(message)
        elif role == "result":
            bubble.setStyleSheet("background:#092b35;border:1px solid #16a79e;border-radius:18px;padding:14px 18px;font-size:14px;")
            message_layout.addWidget(bubble, alignment=Qt.AlignLeft)
            message_layout.addWidget(footer, alignment=Qt.AlignLeft)
            row.addWidget(message)
            row.addStretch()
        else:
            bubble.setStyleSheet("background:#15273c;border:1px solid #607998;border-radius:18px;padding:14px 18px;font-size:14px;")
            message_layout.addWidget(bubble, alignment=Qt.AlignLeft)
            message_layout.addWidget(footer, alignment=Qt.AlignLeft)
            row.addWidget(message)
            row.addStretch()
        self.messages_layout.insertLayout(self.messages_layout.count() - 1, row)
        self.messages_layout.activate()
        self.messages.adjustSize()
        self._schedule_scroll_to_bottom(message)

    def add_user_attachments(self, paths: list[Path]) -> None:
        valid_paths = [path.resolve() for path in paths if path.is_file()]
        if not valid_paths:
            return

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        for path in valid_paths:
            row.addWidget(AttachmentTile(path, removable=False))

        message = QWidget()
        message_layout = QVBoxLayout(message)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(4)
        message_layout.addLayout(row)
        timestamp = QLabel(datetime.now().strftime("%H:%M"))
        timestamp.setStyleSheet("color:#7890ad;font-size:12px;")
        message_layout.addWidget(timestamp, alignment=Qt.AlignRight)

        outer_row = QHBoxLayout()
        outer_row.addStretch()
        outer_row.addWidget(message)
        self.messages_layout.insertLayout(
            self.messages_layout.count() - 1,
            outer_row,
        )
        self.messages_layout.activate()
        self.messages.adjustSize()
        self._schedule_scroll_to_bottom(message)

    def _message_footer(self, text: str) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        timestamp = QLabel(datetime.now().strftime("%H:%M"))
        timestamp.setStyleSheet("color:#7890ad;font-size:12px;")

        copy_button = QPushButton()
        copy_button.setIcon(make_icon("copy", 14, "#7890ad"))
        copy_button.setIconSize(QSize(14, 14))
        copy_button.setFixedSize(20, 20)
        copy_button.setCursor(Qt.PointingHandCursor)
        copy_button.setToolTip("คัดลอกข้อความ")
        copy_button.setStyleSheet(
            "QPushButton { background:transparent; border:none; padding:2px; }"
            "QPushButton:hover { background:#19324d; border-radius:4px; }"
        )
        copy_button.clicked.connect(
            lambda _checked=False, value=text, button=copy_button: self._copy_message(
                value, button
            )
        )

        layout.addWidget(timestamp)
        layout.addWidget(copy_button)
        return footer

    @staticmethod
    def _copy_message(text: str, button: QPushButton) -> None:
        QApplication.clipboard().setText(text)
        generation = int(button.property("copyGeneration") or 0) + 1
        button.setProperty("copyGeneration", generation)
        button.setIcon(make_icon("check", 14, "#43e78f"))
        button.setToolTip("คัดลอกแล้ว")

        def restore() -> None:
            try:
                if button.property("copyGeneration") != generation:
                    return
                button.setIcon(make_icon("copy", 14, "#7890ad"))
                button.setToolTip("คัดลอกข้อความ")
            except RuntimeError:
                pass

        QTimer.singleShot(1000, restore)

    @staticmethod
    def _file_size_text(size: int) -> str:
        if size < 1024:
            return f"{size} ไบต์"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def add_attachment(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return

        row = QHBoxLayout()
        message = QWidget()
        message_layout = QVBoxLayout(message)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(4)

        card = AttachmentCard(str(path))
        card.setObjectName("attachmentCard")
        card.clicked.connect(self.attachment_requested)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(10)

        icon = QLabel()
        icon.setPixmap(make_icon("document", 24, "#eef7ff").pixmap(24, 24))
        icon.setFixedSize(28, 28)
        icon.setAlignment(Qt.AlignCenter)
        icon.setAttribute(Qt.WA_TransparentForMouseEvents)

        details = QVBoxLayout()
        details.setSpacing(2)
        display_name = QFontMetrics(self.font()).elidedText(
            path.name,
            Qt.ElideMiddle,
            320,
        )
        filename = QLabel(display_name)
        filename.setStyleSheet("font-weight:600;font-size:14px;")
        filename.setToolTip(str(path))
        filename.setAttribute(Qt.WA_TransparentForMouseEvents)
        metadata = QLabel(self._file_size_text(size))
        metadata.setObjectName("muted")
        metadata.setStyleSheet("color:#9db0c9;font-size:13px;")
        metadata.setAttribute(Qt.WA_TransparentForMouseEvents)
        details.addWidget(filename)
        details.addWidget(metadata)

        text_width = max(
            QFontMetrics(filename.font()).horizontalAdvance(display_name),
            QFontMetrics(metadata.font()).horizontalAdvance(metadata.text()),
        )
        card.setFixedWidth(max(230, min(430, 14 + 28 + 10 + text_width + 14)))

        card_layout.addWidget(icon)
        card_layout.addLayout(details, 1)
        message_layout.addWidget(card)
        timestamp = QLabel(datetime.now().strftime("%H:%M"))
        timestamp.setStyleSheet("color:#7890ad;font-size:12px;")
        message_layout.addWidget(timestamp, alignment=Qt.AlignLeft)
        row.addWidget(message)
        row.addStretch()
        self.messages_layout.insertLayout(self.messages_layout.count() - 1, row)
        self.messages_layout.activate()
        self.messages.adjustSize()
        self._schedule_scroll_to_bottom(message)

    def _schedule_scroll_to_bottom(self, latest: QWidget) -> None:
        def reveal_latest() -> None:
            self.messages_layout.activate()
            self.messages.adjustSize()
            self.scroll.ensureWidgetVisible(latest, 0, 0)
            self._scroll_to_bottom()

        for delay in (0, 50, 150):
            QTimer.singleShot(delay, reveal_latest)

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_busy(self, busy: bool, status: str = "AI กำลังประมวลผล") -> None:
        self._busy = busy
        self.input.setEnabled(not busy)
        self.permission_mode_button.setEnabled(not busy)
        self._apply_model_controls()
        self.mic_button.setEnabled(
            not busy
            and self._voice_mode == "normal"
            and self.device_rows["microphone"][1].isChecked()
        )
        self.activity_status.setStyleSheet("")
        self.activity_status.setText(("◯  " + status) if busy else "")
        self.send_button.setText("หยุด" if busy else "ส่ง")
        self.send_button.setObjectName("stop" if busy else "primary")
        self.send_button.style().unpolish(self.send_button)
        self.send_button.style().polish(self.send_button)
        self.send_button.setEnabled(True if busy else bool(self.input.toPlainText().strip()))
        self._update_send_enabled()

    def show_activity_error(self, message: str, duration_ms: int = 3000) -> None:
        text = "◯  " + message
        self.activity_status.setStyleSheet("color:#ff6b72;padding:2px 12px;")
        self.activity_status.setText(text)

        def clear_if_current() -> None:
            if not self._busy and self.activity_status.text() == text:
                self.activity_status.clear()
                self.activity_status.setStyleSheet("")

        QTimer.singleShot(duration_ms, clear_if_current)

    def set_mic_enabled(self, enabled: bool) -> None:
        self.mic_button.setEnabled(
            enabled and self._voice_mode == "normal" and not self._busy
        )
        if not enabled:
            self.set_manual_recording(False)

    def set_manual_recording(self, recording: bool) -> None:
        self._manual_recording = recording
        self.mic_button.setIcon(QIcon() if recording else make_icon("microphone", 25))
        self.mic_button.setText("●" if recording else "")
        self.mic_button.setProperty("recording", recording)
        self.mic_button.style().unpolish(self.mic_button)
        self.mic_button.style().polish(self.mic_button)

    def set_voice_mode(self, mode: str) -> None:
        self._voice_mode = mode
        self.auto_mode_button.setChecked(mode == "automatic")
        self.normal_mode_button.setChecked(mode == "normal")
        microphone_enabled = self.device_rows["microphone"][1].isChecked()
        self.mic_button.setEnabled(
            mode == "normal" and microphone_enabled and not self._busy
        )

    def set_nickname(self, nickname: str) -> None:
        self.profile_button.set_nickname(nickname)

    def set_folder(self, path: str | None) -> None:
        if path:
            name = Path(path).name or path
            display_name = QFontMetrics(self.folder_button.font()).elidedText(
                name, Qt.ElideMiddle, 180
            )
            self.folder_button.setText("\u00a0\u00a0" + display_name)
            self.folder_button.setToolTip(path)
            self.remove_folder_button.setVisible(True)
        else:
            self.folder_button.setText("\u00a0\u00a0เลือกโฟลเดอร์")
            self.folder_button.setToolTip("")
            self.remove_folder_button.setVisible(False)

    def set_permission_mode(self, mode: str, emit: bool = False) -> None:
        if mode not in {"ask", "auto"}:
            raise ValueError("Unsupported permission mode")
        changed = mode != self._permission_mode
        self._permission_mode = mode
        label = "ขออนุมัติ" if mode == "ask" else "อนุมัติแทนฉัน"
        self.permission_mode_button.set_label(label)
        if emit and changed:
            self.permission_mode_changed.emit(mode)

    @staticmethod
    def _choice_icon(selected: bool) -> QIcon:
        if selected:
            return make_menu_icon("check", "#43e78f")
        blank = QPixmap(22, 22)
        blank.fill(Qt.transparent)
        return QIcon(blank)

    @staticmethod
    def _popup_above(button: QWidget, menu: QMenu) -> None:
        menu.ensurePolished()
        position = button.mapToGlobal(button.rect().topLeft())
        position.setY(position.y() - menu.sizeHint().height() - 6)
        menu.exec(position)

    def _show_provider_menu(self) -> None:
        menu = QMenu(self)
        for provider, info in PROVIDERS.items():
            action = menu.addAction(info.label)
            action.setIcon(self._choice_icon(provider == self._provider))
            action.triggered.connect(
                lambda _checked=False, selected=provider: self._choose_provider(
                    selected
                )
            )
        self._popup_above(self.ai_provider_button, menu)

    def _choose_provider(self, provider: str) -> None:
        if provider != self._provider:
            self.ai_provider_changed.emit(provider)

    def _show_model_menu(self) -> None:
        settings = self._ai_settings
        if settings is None or not self._model_choices():
            return
        info = PROVIDERS[self._provider]
        current = getattr(settings, f"{info.name}_model")
        menu = QMenu(self)
        for label, value in info.models:
            action = menu.addAction(label)
            action.setIcon(self._choice_icon(value == current))
            action.triggered.connect(
                lambda _checked=False, selected=value, now=current: (
                    self.model_changed.emit(selected) if selected != now else None
                )
            )
        if info.efforts:
            menu.addSeparator()
            effort = _label_for(info.efforts, settings.model_effort)
            effort_menu = menu.addMenu(f"Effort · {effort}")
            effort_menu.setIcon(self._choice_icon(False))
            for label, value in info.efforts:
                action = effort_menu.addAction(label)
                action.setIcon(self._choice_icon(value == settings.model_effort))
                action.triggered.connect(
                    lambda _checked=False, selected=value, now=settings.model_effort: (
                        self.model_effort_changed.emit(selected)
                        if selected != now
                        else None
                    )
                )
        self._popup_above(self.model_button, menu)

    def _model_choices(self) -> tuple:
        info = PROVIDERS.get(self._provider or "")
        return info.models if info else ()

    def set_model_locked(self, locked: bool) -> None:
        self._model_locked = locked
        self._apply_model_controls()

    def _apply_model_controls(self) -> None:
        changeable = not self._busy and not self._model_locked
        self.ai_provider_button.setEnabled(changeable)
        self.model_button.setEnabled(changeable and bool(self._model_choices()))

    def _refresh_model_buttons(self) -> None:
        provider = self._provider
        settings = self._ai_settings
        info = PROVIDERS.get(provider or "")
        self.ai_provider_button.set_label(info.label if info else "เลือก AI")
        if info is None or settings is None:
            label = "เลือกโมเดล"
        else:
            label = _label_for(info.models, getattr(settings, f"{info.name}_model"))
            if info.efforts:
                label += f" · {_label_for(info.efforts, settings.model_effort)}"

        self.model_button.set_label(label)
        self._apply_model_controls()

    def set_ai_unselected(self) -> None:
        # Shown when the saved model could not be loaded: nothing is selected
        # until the user picks one.
        self._provider = None
        self._refresh_model_buttons()

    def set_ai_provider(self, provider: str) -> None:
        self._provider = provider
        self._refresh_model_buttons()

    def set_ai_models(self, settings, selected_provider: str) -> None:
        self._ai_settings = settings
        self._provider = selected_provider
        self._refresh_model_buttons()

    def clear_messages(self, keep_input: bool = False) -> None:
        if not keep_input:
            self.input.clear()
            self.clear_input_attachments()
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                clear_layout(child_layout)
                child_layout.deleteLater()
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def update_device(self, key: str, available: bool, enabled: bool) -> None:
        availability, toggle = self.device_rows[key]
        availability.setStyleSheet(
            "color:#26e68b;font-weight:700;" if available else "color:#ff4d5b;font-weight:700;"
        )
        toggle.blockSignals(True)
        toggle.setChecked(enabled)
        # Let the user probe again when a device was missing at startup.
        toggle.setEnabled(True)
        toggle.blockSignals(False)
        if key == "microphone":
            self.set_mic_enabled(enabled)


class SettingsPage(QWidget):
    back_requested = Signal()
    saved = Signal(dict)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 80)
        top = QFrame()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        back = QPushButton("‹")
        back.clicked.connect(self.back_requested)
        title = QLabel("ตั้งค่า")
        title.setObjectName("pageTitle")
        top_layout.addWidget(back)
        top_layout.addWidget(title)
        top_layout.addStretch()
        outer.addWidget(top)
        form = QFrame()
        form.setObjectName("card")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(28, 24, 28, 24)
        form_layout.setSpacing(10)

        self.gemini_api_key = QLineEdit()
        self.gemini_api_key.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(QLabel("Gemini API key"))
        form_layout.addWidget(self.gemini_api_key)
        save = QPushButton("บันทึก")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        form_layout.addSpacing(8)
        form_layout.addWidget(save, alignment=Qt.AlignRight)
        outer.addWidget(form)
        outer.addStretch()

    def load_values(self, values: dict) -> None:
        self.gemini_api_key.setText(values.get("gemini_api_key", ""))

    def _save(self) -> None:
        self.saved.emit(
            {
                "gemini_api_key": self.gemini_api_key.text().strip(),
            }
        )


class MainWindow(QMainWindow):
    close_requested = Signal()

    def __init__(self):
        super().__init__()
        self._allow_close = False
        self.setWindowTitle("AI Personal Computer")
        self.setMinimumSize(1180, 720)
        self.setStyleSheet(STYLE)
        self.stack = QStackedWidget()
        self.login = LoginPage()
        self.chat = ChatPage()
        self.settings = SettingsPage()
        self.stack.addWidget(self.login)
        self.stack.addWidget(self.chat)
        self.stack.addWidget(self.settings)
        self.setCentralWidget(self.stack)

    def show_login(self) -> None:
        self.stack.setCurrentWidget(self.login)

    def show_chat(self) -> None:
        self.stack.setCurrentWidget(self.chat)

    def show_settings(self) -> None:
        self.stack.setCurrentWidget(self.settings)

    def show_profile_menu(self, anchor, callbacks: dict[str, Callable]) -> None:
        menu = QMenu(self)
        for text, key, icon_kind in (
            ("แก้ไขชื่อผู้ใช้", "rename", "user"),
            ("จัดการใบหน้า", "face", "face"),
            ("เปลี่ยนรหัสผ่าน", "password", "lock"),
            ("ตั้งค่า", "settings", "settings"),
            ("ออกจากระบบ", "logout", "logout"),
        ):
            if key == "logout":
                menu.addSeparator()
            action = menu.addAction(text)
            action.setIcon(
                make_menu_icon(
                    icon_kind,
                    "#ff4d5b" if key == "logout" else "#eef7ff",
                )
            )
            action.triggered.connect(callbacks[key])
        menu.adjustSize()
        position = anchor.mapToGlobal(anchor.rect().topLeft())
        position.setY(position.y() - menu.sizeHint().height() - 8)
        menu.exec(position)

    def closeEvent(self, event) -> None:
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.close_requested.emit()

    def finish_close(self) -> None:
        self._allow_close = True
        self.close()


def numpy_to_pixmap(rgb) -> QPixmap:
    height, width, channels = rgb.shape
    image = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888)
    return QPixmap.fromImage(image.copy())
