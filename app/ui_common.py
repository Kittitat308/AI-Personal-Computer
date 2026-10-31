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
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
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
QComboBox { background:#13243a; border:1px solid #526f91; border-radius:14px; padding:10px 14px; min-height:26px; }
QComboBox:hover { border-color:#2e9bff; background:#17304d; }
QComboBox:disabled { color:#8b98a8; background:#46515f; border-color:#687484; }
QComboBox QAbstractItemView { background:#0b1726; color:#f3f7ff; selection-background-color:#0868c8; }
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



class PillMenuButton(QAbstractButton):
    """Compact rounded button with a chevron that opens a menu."""

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self.label = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        self.set_label(label)

    def set_label(self, label: str) -> None:
        self.label = label
        text_width = QFontMetrics(self.font()).horizontalAdvance(label)
        self.setFixedWidth(min(max(text_width + 46, 72), 280))
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            background = QColor("#0c1829")
            border = QColor("#26384f")
            foreground = QColor("#62748c")
        else:
            hovered = self.underMouse()
            background = QColor("#15304f") if hovered else QColor("#102238")
            border = QColor("#2e9bff") if hovered else QColor("#36506f")
            foreground = QColor("#e6efff")
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(background)
        radius = self.height() / 2 - 1
        painter.drawRoundedRect(
            QRectF(0.6, 0.6, self.width() - 1.2, self.height() - 1.2),
            radius,
            radius,
        )
        painter.setPen(foreground)
        text_rect = self.rect().adjusted(14, 0, -30, 0)
        text = QFontMetrics(self.font()).elidedText(
            self.label, Qt.ElideRight, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        center_x = self.width() - 18
        center_y = self.height() / 2
        painter.setPen(QPen(foreground, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(QPointF(center_x - 4, center_y - 2), QPointF(center_x, center_y + 2))
        painter.drawLine(QPointF(center_x, center_y + 2), QPointF(center_x + 4, center_y - 2))
