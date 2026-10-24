from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QImage,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.face import FACE_GUIDE_HEIGHT_RATIO, FACE_GUIDE_WIDTH_RATIO


STYLE = """
QWidget { background: #020812; color: #f3f7ff; font-family: "Segoe UI", "Noto Sans Thai"; font-size: 16px; }
QLabel { background: transparent; }
QFrame#topBar, QFrame#panel, QFrame#composer, QFrame#card { background: #071527; border: 1px solid #1677d2; border-radius: 18px; }
QFrame#sidebar { background: #030d1a; border: none; }
QFrame#deviceCard { background: #071527; border: 1px solid #145f9f; border-radius: 14px; }
QFrame#attachmentCard { background: #0b2637; border: 1px solid #16a79e; border-radius: 16px; }
QFrame#attachmentCard:hover { background: #10374d; border-color: #2ad5ca; }
QFrame#attachmentTile { background: #10243a; border: 1px solid #526f91; border-radius: 12px; }
QFrame#attachmentTile:hover { border-color: #2298ff; }
QPushButton#attachmentRemove { background: #ff4d5b; border: 1px solid #ff7a85; border-radius: 9px; padding: 0px; }
QPushButton#attachmentRemove:hover { background: #b82837; border-color: #ff8993; }
QLabel#deviceIcon { color: #eef7ff; font-size: 23px; font-weight: 700; }
QLabel#activityStatus { color: #dbe9f8; padding: 2px 12px; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#pageTitle { font-size: 28px; font-weight: 700; }
QLabel#muted { color: #9db0c9; }
QLabel#error { color: #ff6b72; font-size: 13px; min-height: 20px; }
QLabel#success { color: #43e78f; }
QPushButton { background: #13243a; border: 1px solid #66809d; border-radius: 14px; padding: 11px 22px; }
QPushButton:hover { background: rgba(42, 89, 136, 210); border-color: #2e9bff; }
QPushButton:pressed { background: rgba(25, 70, 116, 235); }
QPushButton#primary { background: #087cf0; border-color: #1597ff; font-weight: 600; }
QPushButton#primary:hover { background: #0868c8; border-color: #2e9bff; }
QPushButton#stop { background: #ff3347; color: white; border-color: #ff5969; font-weight: 700; }
QPushButton#stop:hover { background: rgba(255, 80, 97, 225); }
QPushButton#danger, QPushButton#cancel { background: #d93645; color: white; border-color: #f05a67; font-weight: 600; }
QPushButton#danger:hover, QPushButton#cancel:hover { background: #ad2735; border-color: #ff6d79; }
QPushButton:disabled { background: #0b1726; color: #71859f; border: 1px solid #344c68; }
QPushButton#primary:disabled { background: #434c57; color: #aeb8c4; border: 1px solid #697481; }
QLineEdit { background: #13243a; border: 1px solid #526f91; border-radius: 14px; padding: 12px 16px; min-height: 26px; }
QLineEdit:focus { border-color: #2298ff; }
QPlainTextEdit { background: #13243a; border: 1px solid #526f91; border-radius: 14px; padding: 10px 16px; }
QPlainTextEdit:focus { border-color: #2298ff; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: #315f8f; border-radius: 4px; min-height: 48px; }
QScrollBar::handle:vertical:hover { background: #168bea; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px 4px; }
QScrollBar::handle:horizontal { background: #315f8f; border-radius: 4px; min-width: 48px; }
QScrollBar::handle:horizontal:hover { background: #168bea; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QMenu { background: #071527; border: 1px solid #1677d2; border-radius: 12px; padding: 8px; icon-size: 22px; }
QMenu::item { padding: 10px 26px; border-radius: 8px; }
QMenu::item:selected { background: #123765; }
QPushButton#modeButton { padding: 10px 12px; background: #434c57; border-color: #697481; }
QPushButton#modeButton:checked { background: #087cf0; border-color: #1597ff; font-weight: 600; }
QPushButton#modeButton:hover { background: #596572; border-color: #8793a0; }
QPushButton#modeButton:checked:hover { background: #0868c8; }
QPushButton#profileButton { padding: 14px 18px; border-color: #168bea; }
QPushButton#micButton { font-size: 22px; padding: 10px; border-color: #168bea; }
QPushButton#micButton:disabled { background: #434c57; color: #aeb8c4; border-color: #697481; }
QPushButton#micButton[recording="true"] { background: #ff3347; border-color: #ff5969; }
QPushButton#micButton[recording="true"]:hover { background: #c92638; }
QPushButton#removeFolder { color: #ff4d5b; background: transparent; border: 1px solid #8b3440; padding: 8px; font-weight: 700; }
QPushButton#removeFolder:hover { color: white; background: #a52e3b; border-color: #ff5969; }
QDialog#popup { background: #f7f9fc; color: #10243a; border: 1px solid #c9d8e8; }
QDialog#popup QLabel { background: transparent; color: #10243a; }
QDialog#popup QLabel#muted { color: #52677f; }
QDialog#popup QLabel#error { color: #d52d3c; }
QDialog#popup QLineEdit, QDialog#popup QPlainTextEdit { background: white; color: #10243a; border: 1px solid #9eb2c8; }
QDialog#popup QPushButton { background: #edf3f9; color: #10243a; border: 1px solid #9eb2c8; }
QDialog#popup QPushButton:hover { background: #dce9f6; border-color: #168bea; }
QDialog#popup QPushButton#primary { background: #087cf0; color: white; border-color: #1597ff; }
QDialog#popup QPushButton#primary:hover { background: #0868c8; }
QDialog#popup QPushButton#primary:disabled { background: #c7ccd2; color: #737c86; border-color: #aeb5bd; }
QDialog#popup QPushButton#cancel { background: #d93645; color: white; border-color: #f05a67; }
QDialog#popup QPushButton#cancel:hover { background: #ad2735; border-color: #ff6d79; }
QDialog#popup QPushButton#secondaryAction { background: #d8eaff; color: #075bb5; border-color: #78aee4; font-weight: 600; }
QDialog#popup QPushButton#secondaryAction:hover { background: #bddcff; border-color: #168bea; }
QDialog#popup QPushButton#secondaryAction:disabled { background: #c7ccd2; color: #737c86; border-color: #aeb5bd; }
QDialog#popup QPushButton#verifyEmail { background: #e5a900; color: #152238; border-color: #f2c94c; font-weight: 700; }
QDialog#popup QPushButton#verifyEmail:hover { background: #c99000; border-color: #dfb52d; }
QDialog#popup QPushButton#verifyEmail:disabled { background: #c7ccd2; color: #737c86; border-color: #aeb5bd; }
QDialog#popup QPushButton#verifiedEmail:disabled { background: #27a85f; color: white; border-color: #3fc879; font-weight: 700; }
QMessageBox { background: #f7f9fc; }
QMessageBox QLabel { background: transparent; color: #10243a; }
QMessageBox QPushButton { background: #edf3f9; color: #10243a; border: 1px solid #9eb2c8; }
"""


def make_icon(kind: str, size: int = 28, color: str = "#eef7ff") -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), max(2.0, size / 12))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    scale = size / 28.0

    if kind == "camera":
        painter.drawRoundedRect(QRectF(3 * scale, 7 * scale, 22 * scale, 16 * scale), 3, 3)
        painter.drawRect(QRectF(8 * scale, 4 * scale, 7 * scale, 4 * scale))
        painter.drawEllipse(QPointF(14 * scale, 15 * scale), 5 * scale, 5 * scale)
    elif kind == "microphone":
        painter.drawRoundedRect(QRectF(9 * scale, 2 * scale, 10 * scale, 16 * scale), 5, 5)
        path = QPainterPath()
        path.moveTo(5 * scale, 13 * scale)
        path.cubicTo(5 * scale, 23 * scale, 23 * scale, 23 * scale, 23 * scale, 13 * scale)
        painter.drawPath(path)
        painter.drawLine(QPointF(14 * scale, 22 * scale), QPointF(14 * scale, 27 * scale))
        painter.drawLine(QPointF(9 * scale, 27 * scale), QPointF(19 * scale, 27 * scale))
    elif kind == "speaker":
        polygon = QPolygonF([
            QPointF(3 * scale, 11 * scale), QPointF(8 * scale, 11 * scale),
            QPointF(14 * scale, 6 * scale), QPointF(14 * scale, 22 * scale),
            QPointF(8 * scale, 17 * scale), QPointF(3 * scale, 17 * scale),
        ])
        painter.drawPolygon(polygon)
        painter.drawArc(QRectF(13 * scale, 8 * scale, 9 * scale, 12 * scale), -60 * 16, 120 * 16)
        painter.drawArc(QRectF(12 * scale, 4 * scale, 15 * scale, 20 * scale), -55 * 16, 110 * 16)
    elif kind == "user":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(14 * scale, 8 * scale), 5 * scale, 5 * scale)
        painter.drawRoundedRect(QRectF(5 * scale, 15 * scale, 18 * scale, 11 * scale), 8, 8)
    elif kind == "folder":
        path = QPainterPath()
        path.moveTo(3 * scale, 8 * scale)
        path.lineTo(11 * scale, 8 * scale)
        path.lineTo(14 * scale, 11 * scale)
        path.lineTo(25 * scale, 11 * scale)
        path.lineTo(25 * scale, 23 * scale)
        path.lineTo(3 * scale, 23 * scale)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "document":
        path = QPainterPath()
        path.moveTo(6 * scale, 2 * scale)
        path.lineTo(17 * scale, 2 * scale)
        path.lineTo(23 * scale, 8 * scale)
        path.lineTo(23 * scale, 26 * scale)
        path.lineTo(6 * scale, 26 * scale)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(17 * scale, 2 * scale), QPointF(17 * scale, 8 * scale))
        painter.drawLine(QPointF(17 * scale, 8 * scale), QPointF(23 * scale, 8 * scale))
        painter.drawLine(QPointF(9 * scale, 13 * scale), QPointF(20 * scale, 13 * scale))
        painter.drawLine(QPointF(9 * scale, 18 * scale), QPointF(20 * scale, 18 * scale))
        painter.drawLine(QPointF(9 * scale, 23 * scale), QPointF(16 * scale, 23 * scale))
    elif kind == "face":
        painter.drawLine(QPointF(3 * scale, 9 * scale), QPointF(3 * scale, 3 * scale))
        painter.drawLine(QPointF(3 * scale, 3 * scale), QPointF(9 * scale, 3 * scale))
        painter.drawLine(QPointF(19 * scale, 3 * scale), QPointF(25 * scale, 3 * scale))
        painter.drawLine(QPointF(25 * scale, 3 * scale), QPointF(25 * scale, 9 * scale))
        painter.drawLine(QPointF(3 * scale, 19 * scale), QPointF(3 * scale, 25 * scale))
        painter.drawLine(QPointF(3 * scale, 25 * scale), QPointF(9 * scale, 25 * scale))
        painter.drawLine(QPointF(19 * scale, 25 * scale), QPointF(25 * scale, 25 * scale))
        painter.drawLine(QPointF(25 * scale, 25 * scale), QPointF(25 * scale, 19 * scale))
        painter.drawPoint(QPointF(10 * scale, 12 * scale))
        painter.drawPoint(QPointF(18 * scale, 12 * scale))
        painter.drawArc(QRectF(9 * scale, 12 * scale, 10 * scale, 8 * scale), 200 * 16, 140 * 16)
    elif kind == "lock":
        painter.drawRoundedRect(QRectF(5 * scale, 12 * scale, 18 * scale, 13 * scale), 2, 2)
        painter.drawArc(QRectF(8 * scale, 3 * scale, 12 * scale, 15 * scale), 0, 180 * 16)
        painter.drawPoint(QPointF(14 * scale, 18 * scale))
    elif kind == "settings":
        painter.drawEllipse(QPointF(14 * scale, 14 * scale), 5 * scale, 5 * scale)
        for x1, y1, x2, y2 in (
            (14, 2, 14, 7), (14, 21, 14, 26), (2, 14, 7, 14), (21, 14, 26, 14),
            (5, 5, 9, 9), (19, 19, 23, 23), (23, 5, 19, 9), (9, 19, 5, 23),
        ):
            painter.drawLine(QPointF(x1 * scale, y1 * scale), QPointF(x2 * scale, y2 * scale))
    elif kind == "logout":
        painter.drawRoundedRect(QRectF(3 * scale, 4 * scale, 13 * scale, 20 * scale), 2, 2)
        painter.drawLine(QPointF(11 * scale, 14 * scale), QPointF(26 * scale, 14 * scale))
        painter.drawLine(QPointF(21 * scale, 9 * scale), QPointF(26 * scale, 14 * scale))
        painter.drawLine(QPointF(21 * scale, 19 * scale), QPointF(26 * scale, 14 * scale))
    elif kind == "close":
        painter.drawLine(QPointF(6 * scale, 6 * scale), QPointF(22 * scale, 22 * scale))
        painter.drawLine(QPointF(22 * scale, 6 * scale), QPointF(6 * scale, 22 * scale))
    elif kind == "copy":
        painter.drawRoundedRect(QRectF(8 * scale, 4 * scale, 15 * scale, 16 * scale), 2, 2)
        painter.drawRoundedRect(QRectF(4 * scale, 8 * scale, 15 * scale, 16 * scale), 2, 2)
    elif kind == "check":
        painter.drawLine(QPointF(4 * scale, 15 * scale), QPointF(11 * scale, 22 * scale))
        painter.drawLine(QPointF(11 * scale, 22 * scale), QPointF(24 * scale, 6 * scale))
    painter.end()
    return QIcon(pixmap)


def make_menu_icon(kind: str, color: str = "#eef7ff") -> QIcon:
    """Shift an icon right inside the existing menu slot without moving text."""
    canvas = QPixmap(22, 22)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    source = make_icon(kind, 18, color).pixmap(18, 18)
    painter.drawPixmap(4, 2, source)
    painter.end()
    return QIcon(canvas)


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class AttachmentCard(QFrame):
    clicked = Signal(str)

    def __init__(self, source_path: str, parent=None) -> None:
        super().__init__(parent)
        self.source_path = source_path
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("คลิกเพื่อบันทึกไฟล์")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.source_path)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MessageInput(QPlainTextEdit):
    submit_requested = Signal()
    attachments_added = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def insertFromMimeData(self, source) -> None:
        local_urls = [url for url in source.urls() if url.isLocalFile()]
        paths = [
            url.toLocalFile()
            for url in local_urls
            if Path(url.toLocalFile()).is_file()
        ]
        if local_urls:
            if paths:
                self.attachments_added.emit(paths)
            return
        if not paths and source.hasText():
            candidate_urls = [
                value.strip()
                for value in source.text().splitlines()
                if value.strip().lower().startswith("file:///")
            ]
            local_targets = [
                Path(url.toLocalFile())
                for url in map(QUrl, candidate_urls)
                if url.isLocalFile()
            ]
            paths = [
                str(path)
                for path in local_targets
                if path.is_file()
            ]
            if local_targets:
                if paths:
                    self.attachments_added.emit(paths)
                return
        if paths:
            self.attachments_added.emit(paths)
            return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.modifiers() & Qt.ShiftModifier
        ):
            event.accept()
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


class AttachmentTile(QFrame):
    removed = Signal(str)

    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def __init__(self, path: Path, parent=None, removable: bool = True) -> None:
        super().__init__(parent)
        self.path = path.resolve()
        self.setObjectName("attachmentTile")
        self.setFixedSize(64, 64)
        self.setToolTip(str(self.path))

        layout = QGridLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        preview = QLabel()
        preview.setAlignment(Qt.AlignCenter)
        preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        preview.setFixedSize(54, 54)
        if self.path.suffix.lower() in self.IMAGE_SUFFIXES:
            pixmap = QPixmap(str(self.path))
            if not pixmap.isNull():
                preview.setPixmap(
                    pixmap.scaled(
                        50,
                        50,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
        else:
            preview.setPixmap(make_icon("document", 22, "#eef7ff").pixmap(22, 22))
            filename = QLabel(self._compact_filename(self.path, 54))
            filename.setAlignment(Qt.AlignCenter)
            filename.setStyleSheet(
                "color:#dbe9f8;font-size:7px;font-weight:600;background:transparent;"
            )
            filename.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(filename, 0, 0, alignment=Qt.AlignHCenter | Qt.AlignBottom)

        layout.addWidget(preview, 0, 0)
        if removable:
            remove_button = QPushButton()
            remove_button.setObjectName("attachmentRemove")
            remove_button.setIcon(make_icon("close", 8, "#ffffff"))
            remove_button.setIconSize(QSize(8, 8))
            remove_button.setFixedSize(18, 18)
            remove_button.setToolTip("นำไฟล์ออก")
            remove_button.clicked.connect(lambda: self.removed.emit(str(self.path)))
            layout.addWidget(
                remove_button,
                0,
                0,
                alignment=Qt.AlignTop | Qt.AlignRight,
            )

    @staticmethod
    def _compact_filename(path: Path, width: int) -> str:
        suffix = path.suffix
        compact_suffix = suffix.lstrip(".")
        stem = path.stem
        full_name = path.name
        max_characters = max(8, width // 6)
        if len(full_name) <= max_characters:
            return full_name
        stem_length = max(1, max_characters - len(suffix))
        if stem:
            return f"{stem[:stem_length]}{suffix}"
        return f".{compact_suffix}" if suffix else "..."


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(54, 30)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            track = QColor("#343a43")
        elif self.isChecked() and self.underMouse():
            track = QColor("#0868c8")
        elif self.isChecked():
            track = QColor("#168bea")
        elif self.underMouse():
            track = QColor("#707b87")
        else:
            track = QColor("#59636f")
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 1, 54, 28), 14, 14)
        knob_x = 39 if self.isChecked() else 15
        painter.setBrush(QColor("#f4f8ff") if self.isEnabled() else QColor("#71859f"))
        painter.drawEllipse(QPointF(knob_x, 15), 11, 11)


class FaceCameraPreview(QLabel):
    """Camera preview with a stable face-position guide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scan_complete = False

    def set_scan_complete(self, complete: bool) -> None:
        self._scan_complete = complete
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#43e78f" if self._scan_complete else "#2e9bff")
        pen = QPen(color, 3)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        guide_width = self.width() * FACE_GUIDE_WIDTH_RATIO
        guide_height = self.height() * FACE_GUIDE_HEIGHT_RATIO
        guide = QRectF(
            (self.width() - guide_width) / 2,
            (self.height() - guide_height) / 2,
            guide_width,
            guide_height,
        )
        painter.drawEllipse(guide)


class ProfileButton(QAbstractButton):
    def __init__(self, nickname: str = "ผู้ใช้", parent=None):
        super().__init__(parent)
        self.nickname = nickname
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(54)
        self.set_nickname(nickname)

    def set_nickname(self, nickname: str) -> None:
        self.nickname = nickname or "ผู้ใช้"
        metrics = QFontMetrics(self.font())
        width = min(230, max(150, metrics.horizontalAdvance(self.nickname) + 94))
        self.setFixedWidth(width)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background = QColor("#1a3555") if self.underMouse() else QColor("#13243a")
        painter.setPen(QPen(QColor("#2e9bff") if self.underMouse() else QColor("#168bea"), 1.5))
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 14, 14)

        icon_rect = QRectF(15, (self.height() - 23) / 2, 23, 23).toRect()
        make_icon("user", 23).paint(painter, icon_rect)

        painter.setPen(QColor("#f3f7ff"))
        painter.drawText(self.rect(), Qt.AlignCenter, self.nickname)

        arrow_x = self.width() - 22
        arrow_y = self.height() / 2
        painter.setPen(QPen(QColor("#f3f7ff"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(QPointF(arrow_x - 7, arrow_y + 4), QPointF(arrow_x, arrow_y - 4))
        painter.drawLine(QPointF(arrow_x, arrow_y - 4), QPointF(arrow_x + 7, arrow_y + 4))


class PermissionModeButton(QAbstractButton):
    def __init__(self, label: str = "ขออนุมัติ", parent=None):
        super().__init__(parent)
        self.label = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(48)
        self.set_label(label)

    def set_label(self, label: str) -> None:
        self.label = label
        text_width = QFontMetrics(self.font()).horizontalAdvance(label)
        self.setFixedWidth(text_width + 58)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            background = QColor("#0b1726")
            border = QColor("#344c68")
            foreground = QColor("#71859f")
        else:
            background = QColor("#1a3555") if self.underMouse() else QColor("#13243a")
            border = QColor("#2e9bff") if self.underMouse() else QColor("#66809d")
            foreground = QColor("#f3f7ff")
        painter.setPen(QPen(border, 1.5))
        painter.setBrush(background)
        painter.drawRoundedRect(
            QRectF(1, 1, self.width() - 2, self.height() - 2),
            14,
            14,
        )

        painter.setPen(foreground)
        text_rect = self.rect().adjusted(14, 0, -38, 0)
        painter.drawText(text_rect, Qt.AlignCenter, self.label)

        arrow_x = self.width() - 21
        arrow_y = self.height() / 2
        painter.setPen(
            QPen(
                foreground,
                2.5,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        painter.drawLine(
            QPointF(arrow_x - 6, arrow_y + 3),
            QPointF(arrow_x, arrow_y - 3),
        )
        painter.drawLine(
            QPointF(arrow_x, arrow_y - 3),
            QPointF(arrow_x + 6, arrow_y + 3),
        )


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

    def __init__(self):
        super().__init__()
        self._busy = False
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
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
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
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.mic_button)
        input_row.addWidget(self.send_button)
        composer_layout.addWidget(self.attachment_scroll)
        composer_layout.addLayout(folder_row)
        composer_layout.addLayout(input_row)
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

    def clear_messages(self) -> None:
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
        outer.addStretch()


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
