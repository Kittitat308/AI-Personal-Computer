"""Public UI facade kept for backwards-compatible imports."""

from app.ui_common import (
    AttachmentCard,
    AttachmentTile,
    FaceCameraPreview,
    MessageInput,
    PermissionModeButton,
    ProfileButton,
    STYLE,
    ToggleSwitch,
    clear_layout,
    make_icon,
    make_menu_icon,
)
from app.ui_dialogs import (
    FaceScanDialog,
    FormDialog,
    LoadingDialog,
    LoginPage,
    NoticeDialog,
    OtpDialog,
)
from app.ui_pages import ChatPage, MainWindow, SettingsPage, numpy_to_pixmap

__all__ = [
    "AttachmentCard",
    "AttachmentTile",
    "ChatPage",
    "FaceCameraPreview",
    "FaceScanDialog",
    "FormDialog",
    "LoadingDialog",
    "LoginPage",
    "MainWindow",
    "MessageInput",
    "NoticeDialog",
    "OtpDialog",
    "PermissionModeButton",
    "ProfileButton",
    "STYLE",
    "SettingsPage",
    "ToggleSwitch",
    "clear_layout",
    "make_icon",
    "make_menu_icon",
    "numpy_to_pixmap",
]
