from dataclasses import dataclass


@dataclass
class RuntimeState:
    current_user_id: int | None = None
    current_username: str = ""
    current_nickname: str = ""
    camera_available: bool = False
    camera_enabled: bool = False
    microphone_available: bool = False
    microphone_enabled: bool = False
    speaker_available: bool = False
    tts_enabled: bool = False
    assistant_busy: bool = False
    voice_mode: str = "normal"
    allowed_folder: str | None = None

    @property
    def logged_in(self) -> bool:
        return self.current_user_id is not None

    def login(self, user_id: int, username: str, nickname: str) -> None:
        self.current_user_id = user_id
        self.current_username = username
        self.current_nickname = nickname

    def logout(self) -> None:
        self.current_user_id = None
        self.current_username = ""
        self.current_nickname = ""
        self.allowed_folder = None
        self.assistant_busy = False
