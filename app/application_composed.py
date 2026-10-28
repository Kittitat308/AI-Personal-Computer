"""Composition root for the desktop application implementation."""

from app.application_support import *

from app.application_accounts import AccountMixin
from app.application_chat import ChatMixin
from app.application_lifecycle import LifecycleMixin
from app.application_voice import VoiceDeviceMixin


class ThreadBridge(QObject):
    utterance = Signal(object)
    voice_error = Signal(str)
    push_to_talk_pressed = Signal()
    push_to_talk_released = Signal()
    stop_requested = Signal()


class DesktopApplication(
    LifecycleMixin,
    AccountMixin,
    ChatMixin,
    VoiceDeviceMixin,
):
    ATTACHMENT_SUFFIXES = {".docx", ".pdf", ".pptx", ".xlsx"}
    INPUT_ATTACHMENT_SUFFIXES = ATTACHMENT_SUFFIXES | {
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
        ".txt", ".md", ".csv", ".json", ".py", ".html", ".xml",
    }
    MAX_INPUT_ATTACHMENT_SIZE = 25 * 1024 * 1024

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.state = RuntimeState()
        self.database = Database(project_root / "data" / "ai_personal_computer.db")
        self.attachment_cache = tempfile.TemporaryDirectory(prefix="ai_pc_attachments_")
        self.attachment_cache_path = Path(self.attachment_cache.name).resolve()
        self.input_attachment_cache: tempfile.TemporaryDirectory | None = None
        self.face = FaceService(self.database)
        self.controller = GUIController()
        self.stt = GUISTTService()
        self.stt_ready = False
        self.audio_queue = AudioQueue()
        self.tts_ready = False
        self.recovery_email = RecoveryEmailSender(project_root)
        self.wakeword = WakeWordService()
        self.wakeword_listener: WakeWordListener | None = None
        self.wakeword_ready = False
        self.window = MainWindow()
        self.bridge = ThreadBridge()
        self.hotkeys = PushToTalkHotkey(
            on_talk_pressed=self.bridge.push_to_talk_pressed.emit,
            on_talk_released=self.bridge.push_to_talk_released.emit,
            on_stop_pressed=self.bridge.stop_requested.emit,
        )
        self.voice_listener: VoiceListener | None = None
        self.manual_recorder = ManualRecorder()
        self.push_to_talk_held = False
        self.push_to_talk_recording = False
        self.resume_voice_listener_after_push = False
        self.resume_wakeword_after_push = False
        self.current_operation: asyncio.Task | None = None
        self.stt_in_progress = False
        self.operation_canceling = False
        self.session_lock = asyncio.Lock()
        self.latest_frame = None
        self.login_face_count = 0
        self.face_check_running = False
        self.presence_check_running = False
        self.presence_missing_count = 0
        self.registration_dialog: FaceScanDialog | None = None
        self.registration_embeddings: list[np.ndarray] = []
        self.registration_scan_running = False
        self.recovery_dialog: FaceScanDialog | None = None
        self.recovery_face_count = 0
        self.recovery_scan_running = False
        self.recovery_target_user_id: int | None = None
        self.otp_dialog: OtpDialog | None = None
        self.otp_recipient = ""
        self.otp_success_callback = None
        self.otp_controls_account_dialog = False
        self.otp_code = ""
        self.otp_expires_at = 0.0
        self.account_dialog_open = False
        self.logout_in_progress = False
        self.shutdown_started = False
        self.closed = False
        self.startup_errors: list[str] = []

        self.preview_timer = QTimer()
        self.preview_timer.setInterval(80)
        self.preview_timer.timeout.connect(self._update_camera_preview)
        self.login_timer = QTimer()
        self.login_timer.setInterval(1_000)
        self.login_timer.timeout.connect(self._schedule_login_face_check)
        self.presence_timer = QTimer()
        self.presence_timer.setInterval(60_000)
        self.presence_timer.timeout.connect(self._schedule_presence_check)
        self.registration_timer = QTimer()
        self.registration_timer.setInterval(700)
        self.registration_timer.timeout.connect(self._schedule_registration_scan)
        self.recovery_timer = QTimer()
        self.recovery_timer.setInterval(700)
        self.recovery_timer.timeout.connect(self._schedule_recovery_scan)

        self.bridge.utterance.connect(self._on_utterance)
        self.bridge.voice_error.connect(self._on_voice_error)
        self.bridge.push_to_talk_pressed.connect(self._on_push_to_talk_pressed)
        self.bridge.push_to_talk_released.connect(self._on_push_to_talk_released)
        self.bridge.stop_requested.connect(self.stop_current_operation)
        self.window.login.sign_in_requested.connect(self.open_sign_in)
        self.window.login.register_requested.connect(self.open_registration_without_face)
        self.window.close_requested.connect(self._request_shutdown)
        self.window.chat.message_submitted.connect(self._on_typed_message)
        self.window.chat.folder_requested.connect(self.select_folder)
        self.window.chat.folder_cleared.connect(self.clear_folder)
        self.window.chat.permission_mode_changed.connect(
            self.controller.set_admin_permission_mode
        )
        self.window.chat.profile_requested.connect(self.open_profile_menu)
        self.window.chat.toggle_requested.connect(self._on_toggle_requested)
        self.window.chat.voice_mode_changed.connect(self._on_voice_mode_changed)
        self.window.chat.manual_mic_requested.connect(self._on_manual_mic_requested)
        self.window.chat.stop_requested.connect(self.stop_current_operation)
        self.window.chat.attachment_requested.connect(self.save_attachment)
        self.window.settings.back_requested.connect(self._return_to_chat)
