from app.ui_common import *

class LoadingDialog(QDialog):
    def __init__(self, title: str, message: str, parent=None):
        super().__init__(parent)
        self.setObjectName("popup")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setFixedWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        self.title = QLabel(title)
        self.title.setObjectName("pageTitle")
        self.message = QLabel(message)
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addSpacing(12)
        layout.addWidget(self.message)

    def update_message(self, message: str) -> None:
        self.message.setText(message)


class FormDialog(QDialog):
    submitted = Signal(list)
    secondary_requested = Signal()
    field_action_requested = Signal(int)

    def __init__(
        self,
        title: str,
        fields: list[tuple],
        parent=None,
        secondary_text: str | None = None,
        compact_actions: bool = False,
        compact_secondary_actions: bool = False,
        field_actions: dict[int, str] | None = None,
        submit_text: str = "ยืนยัน",
    ):
        super().__init__(parent)
        self.setObjectName("popup")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.inputs: list[QLineEdit] = []
        self.field_labels: list[str] = []
        self.required_fields: list[bool] = []
        self.field_errors: list[QLabel] = []
        self.field_action_buttons: dict[int, QPushButton] = {}
        self.field_verified_values: dict[int, str] = {}
        field_actions = field_actions or {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 30, 34, 30)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        heading.setAlignment(Qt.AlignCenter)
        outer.addWidget(heading)
        outer.addSpacing(24)
        for field_spec in fields:
            if len(field_spec) == 2:
                label_text, secret = field_spec
                required = True
                placeholder = label_text
                show_required_marker = False
            elif len(field_spec) == 3:
                label_text, secret, required = field_spec
                placeholder = label_text
                show_required_marker = required
            elif len(field_spec) == 4:
                label_text, secret, required, placeholder = field_spec
                show_required_marker = required
            else:
                raise ValueError("ข้อมูลช่องกรอกไม่ถูกต้อง")
            self.field_labels.append(label_text)
            self.required_fields.append(required)
            label_row = QHBoxLayout()
            label_row.setSpacing(5)
            label_row.addWidget(QLabel(label_text))
            if show_required_marker:
                required_marker = QLabel("*")
                required_marker.setObjectName("error")
                label_row.addWidget(required_marker)
            label_row.addStretch()
            outer.addLayout(label_row)
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            if secret:
                field.setEchoMode(QLineEdit.Password)
            self.inputs.append(field)
            field_index = len(self.inputs) - 1
            if field_index in field_actions:
                field_row = QHBoxLayout()
                field_row.setSpacing(10)
                field_row.addWidget(field, 1)
                action = QPushButton(field_actions[field_index])
                action.setObjectName("verifyEmail")
                action.setFixedWidth(120)
                action.setEnabled(False)
                action.clicked.connect(
                    lambda _checked=False, index=field_index:
                    self.field_action_requested.emit(index)
                )
                self.field_action_buttons[field_index] = action
                field_row.addWidget(action)
                outer.addLayout(field_row)
            else:
                outer.addWidget(field)
            error = QLabel("")
            error.setObjectName("error")
            error.setFixedHeight(20)
            self.field_errors.append(error)
            outer.addWidget(error)
        self.error = QLabel("")
        self.error.setObjectName("error")
        outer.addWidget(self.error)
        buttons = QHBoxLayout()
        cancel = QPushButton("ยกเลิก")
        cancel.setObjectName("cancel")
        self.submit_button = QPushButton(submit_text)
        self.submit_button.setObjectName("primary")
        self.submit_button.setEnabled(False)
        cancel.clicked.connect(self.reject)
        self.submit_button.clicked.connect(
            lambda: self.submitted.emit([i.text() for i in self.inputs])
        )
        for index, field in enumerate(self.inputs):
            field.textChanged.connect(self._update_submit_enabled)
            if index in self.field_action_buttons:
                field.textChanged.connect(
                    lambda text, field_index=index:
                    self._field_action_text_changed(field_index, text)
                )
            field.textChanged.connect(
                lambda _text, field_index=index: self._clear_field_error(field_index)
            )
        if secondary_text:
            secondary = QPushButton(secondary_text)
            secondary.setObjectName("secondaryAction")
            if compact_secondary_actions:
                secondary.setFixedWidth(160)
                cancel.setFixedWidth(120)
                self.submit_button.setFixedWidth(120)
            secondary.clicked.connect(self.secondary_requested)
            buttons.addWidget(secondary)
            buttons.addStretch()
        elif compact_actions:
            cancel.setFixedWidth(190)
            self.submit_button.setFixedWidth(190)
            buttons.addStretch()
        buttons.addWidget(cancel)
        if compact_actions and not secondary_text:
            buttons.addSpacing(72)
        buttons.addWidget(self.submit_button)
        if compact_actions and not secondary_text:
            buttons.addStretch()
        outer.addLayout(buttons)

    def _update_submit_enabled(self) -> None:
        required_complete = bool(self.inputs) and all(
            not required or field.text().strip()
            for field, required in zip(self.inputs, self.required_fields)
        )
        actions_valid = all(
            not self.inputs[index].text().strip() or self.is_field_verified(index)
            for index in self.field_action_buttons
        )
        self.submit_button.setEnabled(required_complete and actions_valid)

    def set_field_verified(
        self,
        index: int,
        verified: bool,
        value: str | None = None,
    ) -> None:
        button = self.field_action_buttons.get(index)
        if button is None:
            return
        current_value = self.inputs[index].text().strip()
        if verified and current_value:
            self.field_verified_values[index] = (
                current_value if value is None else value.strip()
            )
            button.setText("ยืนยันแล้ว")
            button.setObjectName("verifiedEmail")
            button.setEnabled(False)
        else:
            self.field_verified_values.pop(index, None)
            button.setText("ยืนยัน")
            button.setObjectName("verifyEmail")
            button.setEnabled(bool(current_value))
        button.style().unpolish(button)
        button.style().polish(button)
        self._update_submit_enabled()

    def is_field_verified(self, index: int) -> bool:
        return bool(self.inputs[index].text().strip()) and (
            self.field_verified_values.get(index)
            == self.inputs[index].text().strip()
        )

    def _field_action_text_changed(self, index: int, text: str) -> None:
        verified_value = self.field_verified_values.get(index)
        if verified_value is not None and verified_value != text.strip():
            self.field_verified_values.pop(index, None)
        button = self.field_action_buttons[index]
        verified = self.is_field_verified(index)
        button.setText("ยืนยันแล้ว" if verified else "ยืนยัน")
        button.setObjectName("verifiedEmail" if verified else "verifyEmail")
        button.setEnabled(bool(text.strip()) and not verified)
        button.style().unpolish(button)
        button.style().polish(button)
        self._update_submit_enabled()

    def _clear_field_error(self, index: int) -> None:
        self.field_errors[index].clear()
        self.error.clear()

    def _error_field_index(self, text: str) -> int | None:
        if "ชื่อผู้ใช้หรือรหัสผ่าน" in text:
            for index in range(len(self.field_labels) - 1, -1, -1):
                if "รหัสผ่าน" in self.field_labels[index]:
                    return index
            return None
        if "ชื่อผู้ใช้" in text:
            wanted = "ชื่อผู้ใช้"
        elif "ชื่อเล่น" in text:
            wanted = "ชื่อเล่น"
        elif "รหัสผ่านปัจจุบัน" in text:
            wanted = "รหัสผ่านปัจจุบัน"
        elif "ไม่ตรงกัน" in text:
            for index in range(len(self.field_labels) - 1, -1, -1):
                if "ยืนยันรหัสผ่าน" in self.field_labels[index]:
                    return index
            return None
        elif "รหัสผ่าน" in text:
            preferred = ("รหัสผ่านใหม่", "รหัสผ่าน")
            for wanted in preferred:
                for index, label in enumerate(self.field_labels):
                    if label == wanted:
                        return index
            return None
        elif "Gmail" in text or "อีเมล" in text:
            wanted = "Gmail"
        else:
            return None
        for index, label in enumerate(self.field_labels):
            if wanted in label:
                return index
        return None

    def show_error(self, text: str, field_index: int | None = None) -> None:
        target = self._error_field_index(text) if field_index is None else field_index
        self.show_errors(
            {target: text} if target is not None else {},
            "" if target is not None else text,
        )

    def show_errors(
        self,
        errors: dict[int, str],
        general_error: str = "",
    ) -> None:
        for error in self.field_errors:
            error.clear()
        self.error.clear()
        for target, text in errors.items():
            if 0 <= target < len(self.field_errors):
                self.field_errors[target].setText(text)
        self.error.setText(general_error)


class LoginPage(QWidget):
    sign_in_requested = Signal()
    register_requested = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(80, 38, 80, 54)
        heading = QLabel("AI Personal Computer")
        heading.setObjectName("title")
        heading.setAlignment(Qt.AlignCenter)
        outer.addWidget(heading)
        outer.addSpacing(24)
        self.camera = QLabel("ไม่พบกล้อง")
        self.camera.setAlignment(Qt.AlignCenter)
        self.camera.setMinimumSize(720, 420)
        self.camera.setMaximumSize(900, 520)
        self.camera.setStyleSheet("background:#09131e; border:1px solid #52708e; border-radius:20px;")
        outer.addWidget(self.camera, alignment=Qt.AlignCenter)
        self.status = QLabel("มองกล้องเพื่อเข้าสู่ระบบ")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setObjectName("muted")
        outer.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.setSpacing(20)
        register = QPushButton("สมัครบัญชี")
        register.setObjectName("primary")
        sign_in = QPushButton("ลงชื่อเข้าใช้")
        register.clicked.connect(self.register_requested)
        sign_in.clicked.connect(self.sign_in_requested)
        buttons.addStretch()
        buttons.addWidget(register)
        buttons.addWidget(sign_in)
        buttons.addStretch()
        outer.addLayout(buttons)

    def show_frame(self, pixmap: QPixmap) -> None:
        self.camera.setPixmap(
            pixmap.scaled(self.camera.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )


class FaceScanDialog(QDialog):
    next_requested = Signal()
    retry_requested = Signal()

    def __init__(
        self,
        parent=None,
        title_text: str = "สแกนใบหน้า",
        status_text: str = "มองกล้องเพื่อสแกนใบหน้า",
        show_next_button: bool = True,
        show_retry_button: bool = True,
    ):
        super().__init__(parent)
        self.setObjectName("popup")
        self.setModal(True)
        self.setMinimumWidth(680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 30)
        title = QLabel(title_text)
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        self._complete = False
        self._initial_status = status_text
        self.camera = FaceCameraPreview()
        self.camera.setMinimumSize(600, 340)
        self.camera.setAlignment(Qt.AlignCenter)
        self.camera.setStyleSheet("background:#09131e; border:1px solid #2e9bff; border-radius:18px;")
        layout.addWidget(self.camera)
        self.status = QLabel(status_text)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        cancel = QPushButton("ยกเลิก")
        cancel.setObjectName("cancel")
        self.retry_button = QPushButton("ลองอีกครั้ง")
        self.retry_button.setObjectName("secondaryAction")
        self.retry_button.setEnabled(False)
        self.retry_button.setVisible(show_retry_button)
        self.next_button = QPushButton("ยืนยัน")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.setVisible(show_next_button)
        cancel.clicked.connect(self.reject)
        self.retry_button.clicked.connect(self.retry_requested)
        self.next_button.clicked.connect(self.next_requested)
        buttons.addWidget(cancel, 1)
        buttons.addStretch(1)
        buttons.addWidget(self.retry_button, 1)
        buttons.addWidget(self.next_button, 1)
        layout.addLayout(buttons)

    def show_frame(self, pixmap: QPixmap) -> None:
        if self._complete:
            return
        self.camera.setPixmap(
            pixmap.scaled(self.camera.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def set_complete(self, pixmap: QPixmap | None = None) -> None:
        self._complete = True
        if pixmap is not None:
            self.camera.setPixmap(
                pixmap.scaled(self.camera.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.camera.set_scan_complete(True)
        self.status.setText("สแกนใบหน้าสำเร็จ")
        self.status.setObjectName("success")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.retry_button.setEnabled(True)
        self.next_button.setEnabled(True)

    def reset_scan(self) -> None:
        self._complete = False
        self.camera.set_scan_complete(False)
        self.status.setText(self._initial_status)
        self.status.setObjectName("muted")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.retry_button.setEnabled(False)
        self.next_button.setEnabled(False)


class OtpDialog(QDialog):
    code_completed = Signal(str)
    resend_requested = Signal()

    def __init__(self, masked_email: str, parent=None):
        super().__init__(parent)
        self.setObjectName("popup")
        self.setModal(True)
        self.setMinimumWidth(680)
        self.setFocusPolicy(Qt.StrongFocus)
        self._submitting = False
        self._remaining_seconds = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 34, 42, 32)
        heading = QLabel("ยืนยันอีเมล")
        heading.setObjectName("pageTitle")
        heading.setAlignment(Qt.AlignCenter)
        description = QLabel(
            f"กรอกรหัส 6 หลักที่ส่งไปยัง {masked_email}"
        )
        description.setAlignment(Qt.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(heading)
        layout.addSpacing(14)
        layout.addWidget(description)
        layout.addSpacing(24)

        code_row = QHBoxLayout()
        code_row.setSpacing(12)
        code_row.addStretch()
        self.code_inputs: list[QLabel] = []
        for _index in range(6):
            field = QLabel("")
            field.setFixedSize(66, 72)
            field.setAlignment(Qt.AlignCenter)
            self.code_inputs.append(field)
            code_row.addWidget(field)
        code_row.addStretch()
        layout.addLayout(code_row)

        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setFixedHeight(22)
        self.error.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.error)
        expires = QLabel("รหัสจะหมดอายุใน 10 นาที")
        expires.setObjectName("muted")
        expires.setAlignment(Qt.AlignCenter)
        layout.addWidget(expires)
        layout.addSpacing(24)

        buttons = QHBoxLayout()
        cancel = QPushButton("ยกเลิก")
        cancel.setObjectName("cancel")
        cancel.setFixedWidth(210)
        cancel.setFocusPolicy(Qt.NoFocus)
        self.resend_button = QPushButton("ส่งรหัสอีกครั้ง")
        self.resend_button.setObjectName("secondaryAction")
        self.resend_button.setFixedWidth(210)
        self.resend_button.setFocusPolicy(Qt.NoFocus)
        cancel.clicked.connect(self.reject)
        self.resend_button.clicked.connect(self._request_resend)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addSpacing(72)
        buttons.addWidget(self.resend_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.countdown = QLabel("")
        self.countdown.setObjectName("muted")
        self.countdown.setAlignment(Qt.AlignRight)
        layout.addWidget(self.countdown)

        self.timer = QTimer(self)
        self.timer.setInterval(1_000)
        self.timer.timeout.connect(self._tick)
        self._refresh_code_fields()
        self.set_sending()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus(Qt.OtherFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._submitting:
            event.accept()
            return
        text = event.text()
        if len(text) == 1 and text in "0123456789":
            for field in self.code_inputs:
                if not field.text():
                    field.setText(text)
                    break
            self.error.clear()
            self._refresh_code_fields()
            self._submit_if_complete()
            event.accept()
            return
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            for field in reversed(self.code_inputs):
                if field.text():
                    field.clear()
                    break
            self.error.clear()
            self._refresh_code_fields()
            event.accept()
            return
        event.accept()

    def _submit_if_complete(self) -> None:
        code = "".join(field.text() for field in self.code_inputs)
        if len(code) != 6:
            return
        self._submitting = True
        self._refresh_code_fields()
        self.code_completed.emit(code)

    def _refresh_code_fields(self) -> None:
        active_index = next(
            (index for index, field in enumerate(self.code_inputs) if not field.text()),
            -1,
        )
        for index, field in enumerate(self.code_inputs):
            if self._submitting:
                border = "#aeb5bd"
                width = 1
            elif index == active_index:
                border = "#168bea"
                width = 3
            else:
                border = "#9ebfe3"
                width = 1
            field.setStyleSheet(
                "background:#ffffff; color:#10243a; border:"
                f"{width}px solid {border}; border-radius:12px; "
                "font-size:28px; font-weight:600;"
            )

    def reset_code(self, message: str) -> None:
        self._submitting = False
        for field in self.code_inputs:
            field.clear()
        self.error.setText(message)
        self._refresh_code_fields()
        self.setFocus(Qt.OtherFocusReason)

    def set_sending(self) -> None:
        self.resend_button.setEnabled(False)
        self.resend_button.setText("กำลังส่งรหัส...")
        self.countdown.clear()

    def start_resend_cooldown(self, seconds: int = 60) -> None:
        self._remaining_seconds = seconds
        self.resend_button.setText("ส่งรหัสอีกครั้ง")
        self.resend_button.setEnabled(False)
        self._update_countdown()
        self.timer.start()
        self.setFocus(Qt.OtherFocusReason)

    def show_send_error(self, message: str) -> None:
        self.timer.stop()
        self._remaining_seconds = 0
        self.resend_button.setText("ส่งรหัสอีกครั้ง")
        self.resend_button.setEnabled(True)
        self.countdown.clear()
        self.error.setText(message)

    def _request_resend(self) -> None:
        self.set_sending()
        self.resend_requested.emit()

    def _tick(self) -> None:
        self._remaining_seconds -= 1
        if self._remaining_seconds <= 0:
            self.timer.stop()
            self.resend_button.setEnabled(True)
            self.countdown.clear()
            return
        self._update_countdown()

    def _update_countdown(self) -> None:
        self.countdown.setText(
            f"ส่งได้อีกครั้งใน {self._remaining_seconds} วินาที"
        )


class NoticeDialog(QDialog):
    def __init__(self, title: str, message: str, parent=None, error: bool = False):
        super().__init__(parent)
        self.setObjectName("popup")
        self.setModal(True)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        heading.setStyleSheet("color:#d52d3c;" if error else "color:#10243a;")
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setObjectName("muted")
        close_button = QPushButton("ตกลง")
        close_button.setObjectName("primary")
        close_button.clicked.connect(self.accept)
        layout.addWidget(heading)
        layout.addSpacing(10)
        layout.addWidget(message_label)
        layout.addSpacing(18)
        layout.addWidget(close_button, alignment=Qt.AlignRight)

