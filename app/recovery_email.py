import base64
import threading
from email.message import EmailMessage
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SEND_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]


class RecoveryEmailSender:
    def __init__(self, project_root: Path):
        self.credentials_path = project_root / "google_credentials.json"
        self.token_path = project_root / "secrets" / "gmail_recovery_token.json"
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self._service = None
        self._lock = threading.Lock()

    def _get_service(self, force_reauthorize: bool = False):
        with self._lock:
            if self._service is not None and not force_reauthorize:
                return self._service

            credentials = None
            if self.token_path.exists() and not force_reauthorize:
                credentials = Credentials.from_authorized_user_file(
                    str(self.token_path),
                    SEND_SCOPE,
                )

            if not credentials or not credentials.valid:
                if credentials and credentials.expired and credentials.refresh_token:
                    try:
                        credentials.refresh(Request())
                    except RefreshError:
                        credentials = None
                if not credentials or not credentials.valid:
                    if not self.credentials_path.exists():
                        raise FileNotFoundError("ไม่พบไฟล์ Google Credentials")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_path),
                        SEND_SCOPE,
                    )
                    credentials = flow.run_local_server(port=0)
                self.token_path.write_text(
                    credentials.to_json(),
                    encoding="utf-8",
                )

            self._service = build(
                "gmail",
                "v1",
                credentials=credentials,
                cache_discovery=False,
            )
            return self._service

    def send_otp(self, recipient: str, code: str) -> None:
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = "รหัสกู้คืนรหัสผ่าน AI Personal Computer"
        message.set_content(
            "รหัสยืนยันสำหรับกู้คืนรหัสผ่านของคุณคือ "
            f"{code}\n\nรหัสนี้จะหมดอายุใน 10 นาที "
            "หากคุณไม่ได้เป็นผู้ขอรหัสนี้ สามารถละเว้นอีเมลฉบับนี้ได้"
        )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

        def execute(service):
            service.users().messages().send(
                userId="me",
                body={"raw": raw},
            ).execute()

        try:
            execute(self._get_service())
        except RefreshError:
            execute(self._get_service(force_reauthorize=True))
