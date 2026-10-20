import base64
import html
import re
import threading
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MAX_RESULTS = 20
MAX_BODY_CHARS = 6000
MAX_TOTAL_BODY_CHARS = 12000
LOCAL_TIMEZONE = "Asia/Bangkok"

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
}

URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)

FOOTER_PATTERN = re.compile(
    r"^(?:unsubscribe|manage (?:email )?preferences|"
    r"view (?:this email )?in (?:your )?browser|"
    r"follow us(?: on)?|connect with us|privacy policy|"
    r"ยกเลิกรับข่าวสาร|จัดการการตั้งค่าอีเมล|"
    r"ดูอีเมลนี้ในเบราว์เซอร์)\b",
    re.IGNORECASE,
)


class GmailReader:

    def __init__(self, project_root, skill_directory):

        self.credentials_path = Path(project_root) / "google_credentials.json"
        self.token_path = Path(skill_directory) / "gmail_token.json"
        self.service = None
        self.service_lock = threading.Lock()

    def get_service(self, force_reauthorize=False):

        with self.service_lock:

            if self.service is not None and not force_reauthorize:
                return self.service

            credentials = None

            if self.token_path.exists() and not force_reauthorize:
                credentials = Credentials.from_authorized_user_file(
                    str(self.token_path),
                    SCOPES,
                )

            if not credentials or not credentials.valid:

                if (
                    credentials
                    and credentials.expired
                    and credentials.refresh_token
                ):
                    try:
                        credentials.refresh(Request())
                    except RefreshError:
                        credentials = None

                if not credentials or not credentials.valid:

                    if not self.credentials_path.exists():
                        raise FileNotFoundError(
                            "google_credentials.json was not found"
                        )

                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_path),
                        SCOPES,
                    )
                    credentials = flow.run_local_server(port=0)

                self.token_path.write_text(
                    credentials.to_json(),
                    encoding="utf-8",
                )

            self.service = build(
                "gmail",
                "v1",
                credentials=credentials,
                cache_discovery=False,
            )

            return self.service

    def execute_request(self, request_factory):

        try:
            return request_factory(self.get_service()).execute()
        except RefreshError:
            return request_factory(
                self.get_service(force_reauthorize=True)
            ).execute()

    def build_query(
        self,
        start_date,
        end_date,
        read_status,
        sender_email,
    ):

        read_status = str(read_status).strip().lower()

        if read_status not in {"all", "read", "unread"}:
            raise ValueError("read_status must be all, read, or unread")

        sender_email = str(sender_email).strip()

        if sender_email and (
            sender_email.count("@") != 1
            or any(character.isspace() for character in sender_email)
            or any(character in "<>" for character in sender_email)
        ):
            raise ValueError("sender_email must be a valid email address")

        if bool(start_date) != bool(end_date):
            raise ValueError(
                "start_date and end_date must be supplied together"
            )

        query_parts = ["in:inbox"]

        if read_status != "all":
            query_parts.append(f"is:{read_status}")

        if sender_email:
            query_parts.append(f"from:{sender_email}")

        if start_date:

            try:
                local_timezone = ZoneInfo(LOCAL_TIMEZONE)
            except ZoneInfoNotFoundError as error:
                raise ValueError("Unknown IANA timezone") from error

            try:
                start = datetime.strptime(
                    start_date,
                    "%Y-%m-%d",
                ).replace(tzinfo=local_timezone)
                end = datetime.strptime(
                    end_date,
                    "%Y-%m-%d",
                ).replace(tzinfo=local_timezone)
            except ValueError as error:
                raise ValueError(
                    "Dates must use YYYY-MM-DD format"
                ) from error

            if end <= start:
                raise ValueError("end_date must be after start_date")

            query_parts.extend([
                f"after:{int(start.timestamp())}",
                f"before:{int(end.timestamp())}",
            ])

        return " ".join(query_parts)

    def read_emails(
        self,
        start_date="",
        end_date="",
        read_status="all",
        max_results=10,
        content_level="metadata",
        sender_email="",
    ):

        gmail_query = self.build_query(
            start_date,
            end_date,
            read_status,
            sender_email,
        )
        content_level = str(content_level).strip().lower()

        if content_level not in {"metadata", "full"}:
            raise ValueError("content_level must be metadata or full")

        max_results = max(1, min(int(max_results), MAX_RESULTS))
        search_result = self.execute_request(
            lambda service: service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                maxResults=max_results,
            )
        )

        emails = []
        remaining_body_chars = MAX_TOTAL_BODY_CHARS

        for target in search_result.get("messages", []):
            email = self.get_message(
                target["id"],
                include_body=content_level == "full",
                body_limit=min(MAX_BODY_CHARS, remaining_body_chars),
            )
            emails.append(email)
            remaining_body_chars -= len(email.get("body", ""))

        return {
            "returned_count": len(emails),
            "truncated": bool(search_result.get("nextPageToken")),
            "content_level": content_level,
            "emails": emails,
        }

    def get_message(self, message_id, include_body, body_limit):

        if not include_body:
            result = self.execute_request(
                lambda service: service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=[
                        "From",
                        "To",
                        "Subject",
                        "Date",
                    ],
                )
            )
            headers = self.get_headers(result)

            return self.build_email_result(
                result,
                headers,
                body=None,
                body_truncated=False,
            )

        result = self.execute_request(
            lambda service: service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="raw",
            )
        )
        raw = result.get("raw", "")

        if not raw:
            raise ValueError("Gmail message did not include raw content")

        raw += "=" * (-len(raw) % 4)
        message = BytesParser(policy=policy.default).parsebytes(
            base64.urlsafe_b64decode(raw)
        )
        body = ""
        body_part = message.get_body(preferencelist=("plain", "html"))

        if body_part is not None:
            body = body_part.get_content()

            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")

        body = self.clean_body(body)
        body, body_truncated = self.truncate_body(
            body,
            max(0, body_limit),
        )
        headers = {
            "from": str(message.get("From", "")),
            "to": str(message.get("To", "")),
            "subject": str(message.get("Subject", "")),
            "date": str(message.get("Date", "")),
        }

        return self.build_email_result(
            result,
            headers,
            body=body,
            body_truncated=body_truncated,
        )

    def get_headers(self, result):

        headers = {}

        for header in result.get("payload", {}).get("headers", []):
            name = header.get("name", "").lower()

            if name:
                headers[name] = header.get("value", "")

        return headers

    def build_email_result(
        self,
        result,
        headers,
        body,
        body_truncated,
    ):

        email = {
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "read_status": (
                "unread"
                if "UNREAD" in result.get("labelIds", [])
                else "read"
            ),
        }

        if body is not None:
            email["body"] = body
            email["body_truncated"] = body_truncated

        return email

    def clean_body(self, body):

        if not isinstance(body, str):
            return ""

        body = re.sub(
            r"<(script|style)\b[^>]*>.*?</\1>",
            " ",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        body = re.sub(r"<[^>]+>", " ", body)
        body = html.unescape(body)
        body = URL_PATTERN.sub(self.clean_url, body)
        body = "".join(
            character
            for character in body
            if character in "\n\t" or ord(character) >= 32
        )

        cleaned_lines = []
        seen_lines = set()

        for raw_line in body.splitlines():
            line = re.sub(r"[ \t]+", " ", raw_line).strip()

            if not line or FOOTER_PATTERN.match(line):
                continue

            identity = line.casefold()

            if len(identity) >= 20 and identity in seen_lines:
                continue

            if len(identity) >= 20:
                seen_lines.add(identity)

            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def clean_url(self, match):

        url = match.group(0).rstrip(".,);]")

        try:
            parts = urlsplit(url)
            query = [
                (key, value)
                for key, value in parse_qsl(
                    parts.query,
                    keep_blank_values=True,
                )
                if (
                    not key.lower().startswith("utm_")
                    and key.lower() not in TRACKING_PARAMETERS
                )
            ]

            return urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    parts.path,
                    urlencode(query, doseq=True),
                    "",
                )
            )
        except Exception:
            return url

    def truncate_body(self, body, limit):

        if len(body) <= limit:
            return body, False

        if limit <= 0:
            return "", bool(body)

        marker = "\n[content omitted]\n"

        if limit <= len(marker):
            return body[:limit], True

        available = limit - len(marker)
        head_size = int(available * 0.7)
        tail_size = available - head_size

        return (
            body[:head_size].rstrip()
            + marker
            + body[-tail_size:].lstrip(),
            True,
        )
