from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


STYLE = """
QWidget { background: #020812; color: #f3f7ff; font-family: "Segoe UI", "Noto Sans Thai"; font-size: 16px; }
QFrame#topBar, QFrame#panel, QFrame#composer, QFrame#card { background: #071527; border: 1px solid #1677d2; border-radius: 18px; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#pageTitle { font-size: 28px; font-weight: 700; }
QLabel#muted { color: #9db0c9; }
QLabel#error { color: #ff6b72; font-size: 13px; min-height: 20px; }
QLabel#success { color: #43e78f; }
QPushButton { background: #13243a; border: 1px solid #66809d; border-radius: 14px; padding: 11px 22px; }
QPushButton:hover { background: #1a3555; border-color: #2e9bff; }
QPushButton#primary { background: #087cf0; border-color: #1597ff; font-weight: 600; }
QPushButton#danger { color: #ff666d; border-color: #7d343d; }
QPushButton:disabled { background: #0b1726; color: #71859f; border: 1px solid #344c68; }
QPushButton#primary:disabled { background: #10243a; color: #667f9e; border: 1px solid #365c82; }
QLineEdit { background: #13243a; border: 1px solid #526f91; border-radius: 14px; padding: 12px 16px; min-height: 26px; }
QLineEdit:focus { border-color: #2298ff; }
QPlainTextEdit { background: #13243a; border: 1px solid #526f91; border-radius: 14px; padding: 10px 16px; }
QPlainTextEdit:focus { border-color: #2298ff; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #071527; width: 9px; margin: 5px 1px; }
QScrollBar::handle:vertical { background: #486a98; border-radius: 4px; min-height: 48px; }
QMenu { background: #071527; border: 1px solid #1677d2; border-radius: 12px; padding: 8px; }
QMenu::item { padding: 10px 26px; border-radius: 8px; }
QMenu::item:selected { background: #123765; }
QCheckBox::indicator { width: 48px; height: 25px; }
"""


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class MessageInput(QPlainTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.modifiers() & Qt.ShiftModifier
        ):
            event.accept()
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


class LoadingDialog(QDialog):
    def __init__(self, title: str, message: str, parent=None):
        super().__init__(parent)
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

    def __init__(
        self,
        title: str,
        fields: list[tuple[str, bool]],
        parent=None,
        secondary_text: str | None = None,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.inputs: list[QLineEdit] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 30, 34, 30)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        heading.setAlignment(Qt.AlignCenter)
        outer.addWidget(heading)
        outer.addSpacing(24)
        for label_text, secret in fields:
            outer.addWidget(QLabel(label_text))
            field = QLineEdit()
            field.setPlaceholderText(label_text)
            if secret:
                field.setEchoMode(QLineEdit.Password)
            self.inputs.append(field)
            outer.addWidget(field)
            error = QLabel("")
            error.setObjectName("error")
            outer.addWidget(error)
        self.error = QLabel("")
        self.error.setObjectName("error")
        outer.addWidget(self.error)
        buttons = QHBoxLayout()
        cancel = QPushButton("ยกเลิก")
        self.submit_button = QPushButton("ยืนยัน")
        self.submit_button.setObjectName("primary")
        self.submit_button.setEnabled(False)
        cancel.clicked.connect(self.reject)
        self.submit_button.clicked.connect(
            lambda: self.submitted.emit([i.text() for i in self.inputs])
        )
        for field in self.inputs:
            field.textChanged.connect(self._update_submit_enabled)
        if secondary_text:
            secondary = QPushButton(secondary_text)
            secondary.clicked.connect(self.secondary_requested)
            buttons.addWidget(secondary)
            buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.submit_button)
        outer.addLayout(buttons)

    def _update_submit_enabled(self) -> None:
        self.submit_button.setEnabled(
            bool(self.inputs) and all(field.text().strip() for field in self.inputs)
        )

    def show_error(self, text: str) -> None:
        self.error.setText(text)


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

    def __init__(
        self,
        parent=None,
        title_text: str = "สแกนใบหน้า",
        status_text: str = "มองกล้องเพื่อสแกนใบหน้า",
        show_next_button: bool = True,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setMinimumWidth(680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 30)
        title = QLabel(title_text)
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        self.camera = QLabel()
        self.camera.setMinimumSize(600, 340)
        self.camera.setAlignment(Qt.AlignCenter)
        self.camera.setStyleSheet("background:#09131e; border:1px solid #2e9bff; border-radius:18px;")
        layout.addWidget(self.camera)
        self.status = QLabel(status_text)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        cancel = QPushButton("ยกเลิก")
        self.next_button = QPushButton("ถัดไป")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.setVisible(show_next_button)
        cancel.clicked.connect(self.reject)
        self.next_button.clicked.connect(self.next_requested)
        buttons.addWidget(cancel)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

    def show_frame(self, pixmap: QPixmap) -> None:
        self.camera.setPixmap(
            pixmap.scaled(self.camera.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def set_complete(self) -> None:
        self.status.setText("สแกนใบหน้าสำเร็จ")
        self.status.setObjectName("success")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.next_button.setEnabled(True)


class ChatPage(QWidget):
    message_submitted = Signal(str)
    folder_requested = Signal()
    settings_requested = Signal()
    profile_requested = Signal(object)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 26)
        top = QFrame()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        title = QLabel("AI Personal Computer")
        title.setObjectName("title")
        self.ready_status = QLabel("●  พร้อมใช้งาน")
        self.mic_status = QLabel("●  ไมโครโฟนเปิด")
        self.ready_status.setStyleSheet("color:#43e78f;font-weight:600;")
        self.mic_status.setStyleSheet("color:#43e78f;font-weight:600;")
        settings = QPushButton("⚙")
        profile = QPushButton("ผู้ใช้")
        settings.clicked.connect(self.settings_requested)
        profile.clicked.connect(lambda: self.profile_requested.emit(profile))
        top_layout.addWidget(title)
        top_layout.addWidget(self.ready_status)
        top_layout.addWidget(self.mic_status)
        top_layout.addStretch()
        top_layout.addWidget(settings)
        top_layout.addWidget(profile)
        outer.addWidget(top)

        center = QHBoxLayout()
        center.addStretch(2)
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
        composer_layout = QHBoxLayout(composer)
        folder = QPushButton("▱  เลือกโฟลเดอร์")
        folder.clicked.connect(self.folder_requested)
        self.input = MessageInput()
        self.input.setPlaceholderText("พิมพ์ข้อความ...")
        self.input.setMinimumHeight(54)
        self.input.setMaximumHeight(110)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.submit_requested.connect(self._submit)
        self.input.textChanged.connect(self._update_send_enabled)
        self.send_button = QPushButton("ส่ง")
        self.send_button.setObjectName("primary")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._submit)
        composer_layout.addWidget(folder)
        composer_layout.addWidget(self.input, 1)
        composer_layout.addWidget(self.send_button)
        column.addWidget(composer)
        center.addLayout(column, 6)
        center.addStretch(2)
        outer.addLayout(center, 1)

    def _submit(self) -> None:
        text = self.input.toPlainText().strip()
        if text:
            self.input.clear()
            self.message_submitted.emit(text)

    def _update_send_enabled(self) -> None:
        self.send_button.setEnabled(
            self.input.isEnabled() and bool(self.input.toPlainText().strip())
        )

    def add_message(self, text: str, role: str) -> None:
        row = QHBoxLayout()
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(620)
        if role == "user":
            bubble.setStyleSheet("background:#075bb5;border:1px solid #1597ff;border-radius:18px;padding:14px 18px;")
            row.addStretch()
            row.addWidget(bubble)
        elif role == "result":
            bubble.setStyleSheet("background:#092b35;border:1px solid #16a79e;border-radius:18px;padding:14px 18px;")
            row.addWidget(bubble)
            row.addStretch()
        else:
            bubble.setStyleSheet("background:#15273c;border:1px solid #607998;border-radius:18px;padding:14px 18px;")
            row.addWidget(bubble)
            row.addStretch()
        self.messages_layout.insertLayout(self.messages_layout.count() - 1, row)
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def set_busy(self, busy: bool) -> None:
        self.ready_status.setText("●  กำลังทำงาน" if busy else "●  พร้อมใช้งาน")
        self.ready_status.setStyleSheet(
            "color:#f5c451;font-weight:600;"
            if busy
            else "color:#43e78f;font-weight:600;"
        )
        self.input.setEnabled(not busy)
        self._update_send_enabled()

    def set_mic_enabled(self, enabled: bool) -> None:
        self.mic_status.setText("●  ไมโครโฟนเปิด" if enabled else "●  ไมโครโฟนปิด")
        self.mic_status.setStyleSheet(
            "color:#43e78f;font-weight:600;"
            if enabled
            else "color:#8393a8;font-weight:600;"
        )


class SettingsPage(QWidget):
    back_requested = Signal()
    toggle_requested = Signal(str, bool)
    test_requested = Signal(str)

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
        outer.addSpacing(55)
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMaximumWidth(1080)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(28, 28, 28, 28)
        self.rows = {}
        for key, title_text, test_text in (
            ("camera", "กล้อง", "ทดสอบกล้อง"),
            ("microphone", "ไมโครโฟน", "ทดสอบไมโครโฟน"),
            ("tts", "เสียงพูด", "ทดสอบเสียง"),
        ):
            card = QFrame()
            card.setObjectName("card")
            row = QHBoxLayout(card)
            texts = QVBoxLayout()
            title = QLabel(title_text)
            title.setObjectName("pageTitle")
            status = QLabel("ไม่พบอุปกรณ์")
            status.setObjectName("muted")
            texts.addWidget(title)
            texts.addWidget(status)
            toggle = QCheckBox()
            toggle.toggled.connect(lambda value, item=key: self.toggle_requested.emit(item, value))
            test = QPushButton(test_text)
            test.clicked.connect(lambda _=False, item=key: self.test_requested.emit(item))
            row.addLayout(texts, 1)
            row.addWidget(toggle)
            row.addWidget(test)
            panel_layout.addWidget(card)
            self.rows[key] = (status, toggle, test)
        outer.addWidget(panel, alignment=Qt.AlignHCenter)
        outer.addStretch()

    def update_device(self, key: str, available: bool, enabled: bool, label: str) -> None:
        status, toggle, test = self.rows[key]
        status.setText(("●  " if available else "○  ") + label)
        toggle.blockSignals(True)
        toggle.setChecked(enabled)
        toggle.blockSignals(False)
        test.setEnabled(available and enabled)


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

    def show_profile_menu(self, anchor, username: str, callbacks: dict[str, Callable]) -> None:
        menu = QMenu(self)
        header = QAction(username, menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()
        for text, key in (
            ("แก้ไขข้อมูลผู้ใช้", "rename"),
            ("จัดการใบหน้า", "face"),
            ("เปลี่ยนรหัสผ่าน", "password"),
            ("ออกจากระบบ", "logout"),
        ):
            action = menu.addAction(text)
            action.triggered.connect(callbacks[key])
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

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
