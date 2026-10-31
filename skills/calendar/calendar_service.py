import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
LOCAL_TIMEZONE = "Asia/Bangkok"
MAX_RETURNED_EVENTS = 100
MAX_SCANNED_EVENTS = 1000
DEFAULT_RANGE_DAYS = 365
DEFAULT_TIMED_REMINDER_MINUTES = 15
DEFAULT_ALL_DAY_REMINDER_MINUTES = 900
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class CalendarService:

    def __init__(self, project_root, token_path):

        self.credentials_path = (
            Path(project_root) / "secrets" / "google_credentials.json"
        )
        self.token_path = Path(token_path) if token_path else None
        self.service = None
        self.service_lock = threading.Lock()

    def get_service(self, force_reauthorize=False):

        with self.service_lock:

            if self.service is not None and not force_reauthorize:
                return self.service

            if self.token_path is None:
                raise RuntimeError("No signed-in user data directory is set")

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

                self.token_path.parent.mkdir(parents=True, exist_ok=True)
                self.token_path.write_text(
                    credentials.to_json(),
                    encoding="utf-8",
                )

            self.service = build(
                "calendar",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )

            return self.service

    def parse_date(self, value, field_name):

        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{field_name} must use YYYY-MM-DD format"
            ) from error

    def parse_time(self, value, field_name):

        try:
            parsed = time.fromisoformat(str(value))
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{field_name} must use HH:MM format"
            ) from error

        if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
            raise ValueError(f"{field_name} must use HH:MM format")

        return parsed

    def local_datetime(self, date_value, time_value):

        return datetime.combine(
            date_value,
            time_value,
            tzinfo=ZoneInfo(LOCAL_TIMEZONE),
        )

    def current_local_datetime(self):

        return datetime.now(ZoneInfo(LOCAL_TIMEZONE))

    def normalize_event(self, event):

        start_data = event.get("start", {})
        end_data = event.get("end", {})
        all_day = "date" in start_data

        return {
            "event_id": event.get("id", ""),
            "summary": event.get("summary", ""),
            "start": (
                start_data.get("date")
                or start_data.get("dateTime", "")
            ),
            "end": (
                end_data.get("date")
                or end_data.get("dateTime", "")
            ),
            "all_day": all_day,
            "location": event.get("location", ""),
            "description": event.get("description", ""),
            "status": event.get("status", ""),
        }

    def event_start(self, event):

        start_data = event.get("start", {})

        if "date" in start_data:
            return self.local_datetime(
                self.parse_date(start_data["date"], "event start date"),
                time.min,
            )

        value = start_data.get("dateTime", "")

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).astimezone(ZoneInfo(LOCAL_TIMEZONE))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Calendar event has an invalid start") from error

    def build_read_range(
        self,
        date_scope="upcoming",
        start_date="",
        end_date="",
    ):

        date_scope = str(date_scope or "upcoming").strip().lower()
        supported_scopes = {
            "today",
            "tomorrow",
            "yesterday",
            "this_week",
            "last_week",
            "next_week",
            "this_month",
            "last_month",
            "next_month",
            "upcoming",
            "past",
            "all",
            "custom",
        }

        if date_scope not in supported_scopes:
            raise ValueError("Unsupported date_scope")

        if bool(start_date) != bool(end_date):
            raise ValueError(
                "start_date and end_date must be supplied together"
            )

        if date_scope != "custom" and (start_date or end_date):
            raise ValueError(
                "start_date and end_date are only valid with custom date_scope"
            )

        if date_scope == "custom":

            if not start_date:
                raise ValueError(
                    "custom date_scope requires start_date and end_date"
                )

            start_value = self.parse_date(start_date, "start_date")
            end_value = self.parse_date(end_date, "end_date")

            if end_value <= start_value:
                raise ValueError("end_date must be after start_date")

            return (
                self.local_datetime(start_value, time.min),
                self.local_datetime(end_value, time.min),
            )

        if date_scope == "all":
            return None, None

        now = self.current_local_datetime()
        today = now.date()

        if date_scope == "upcoming":
            return now, now + timedelta(days=DEFAULT_RANGE_DAYS)

        if date_scope == "past":
            return now - timedelta(days=DEFAULT_RANGE_DAYS), now

        if date_scope == "today":
            start_value = today
            end_value = today + timedelta(days=1)
        elif date_scope == "tomorrow":
            start_value = today + timedelta(days=1)
            end_value = start_value + timedelta(days=1)
        elif date_scope == "yesterday":
            start_value = today - timedelta(days=1)
            end_value = today
        elif date_scope in {"this_week", "last_week", "next_week"}:
            this_week = today - timedelta(days=today.weekday())
            week_offset = {
                "last_week": -7,
                "this_week": 0,
                "next_week": 7,
            }[date_scope]
            start_value = this_week + timedelta(days=week_offset)
            end_value = start_value + timedelta(days=7)
        else:
            this_month = today.replace(day=1)

            if date_scope == "last_month":
                end_value = this_month
                start_value = (this_month - timedelta(days=1)).replace(day=1)
            elif date_scope == "this_month":
                start_value = this_month
                end_value = (
                    this_month.replace(day=28) + timedelta(days=4)
                ).replace(day=1)
            else:
                start_value = (
                    this_month.replace(day=28) + timedelta(days=4)
                ).replace(day=1)
                end_value = (
                    start_value.replace(day=28) + timedelta(days=4)
                ).replace(day=1)

        return (
            self.local_datetime(start_value, time.min),
            self.local_datetime(end_value, time.min),
        )

    def read_events(
        self,
        date_scope="upcoming",
        start_date="",
        end_date="",
        weekdays=None,
        start_time="",
        end_time="",
    ):

        start, end = self.build_read_range(
            date_scope,
            start_date,
            end_date,
        )

        if bool(start_time) != bool(end_time):
            raise ValueError(
                "start_time and end_time must be supplied together"
            )

        time_start = None
        time_end = None

        if start_time:
            time_start = self.parse_time(start_time, "start_time")
            time_end = self.parse_time(end_time, "end_time")

            if time_end <= time_start:
                raise ValueError("end_time must be after start_time")

        weekday_numbers = set()

        for weekday in weekdays or []:
            normalized = str(weekday).strip().lower()

            if normalized not in WEEKDAYS:
                raise ValueError(f"Unsupported weekday: {weekday}")

            weekday_numbers.add(WEEKDAYS[normalized])

        service = self.get_service()
        page_token = None
        events = []
        scanned_events = 0
        source_truncated = False

        while True:
            query = {
                "calendarId": "primary",
                "singleEvents": True,
                "showDeleted": False,
                "orderBy": "startTime",
                "maxResults": 250,
                "pageToken": page_token,
            }

            if start is not None:
                query["timeMin"] = start.isoformat()
                query["timeMax"] = end.isoformat()

            result = (
                service.events()
                .list(**query)
                .execute()
            )

            for raw_event in result.get("items", []):

                if weekday_numbers and (
                    self.event_start(raw_event).weekday()
                    not in weekday_numbers
                ):
                    continue

                if time_start is not None:

                    if "date" in raw_event.get("start", {}):
                        continue

                    event_time = self.event_start(raw_event).time().replace(
                        tzinfo=None
                    )

                    if not time_start <= event_time < time_end:
                        continue

                events.append(raw_event)

            scanned_events += len(result.get("items", []))
            page_token = result.get("nextPageToken")

            if not page_token:
                break

            if (
                len(events) > MAX_RETURNED_EVENTS
                or scanned_events >= MAX_SCANNED_EVENTS
            ):
                source_truncated = True
                break

        events.sort(key=self.event_start)
        selected = events[:MAX_RETURNED_EVENTS]

        return {
            "date_scope": str(date_scope or "upcoming").strip().lower(),
            "returned_count": len(selected),
            "truncated": source_truncated or len(events) > len(selected),
            "timezone": LOCAL_TIMEZONE,
            "events": [
                self.normalize_event(event)
                for event in selected
            ],
        }

    def build_timing(self, timing):

        if not isinstance(timing, dict):
            raise ValueError("timing must be an object")

        all_day = timing.get("all_day")

        if not isinstance(all_day, bool):
            raise ValueError("timing.all_day must be boolean")

        start_date = self.parse_date(
            timing.get("start_date"),
            "timing.start_date",
        )
        end_date = self.parse_date(
            timing.get("end_date"),
            "timing.end_date",
        )

        if all_day:

            if end_date <= start_date:
                raise ValueError(
                    "All-day timing.end_date must be after start_date"
                )

            return {
                "start": {
                    "date": start_date.isoformat(),
                },
                "end": {
                    "date": end_date.isoformat(),
                },
            }

        start_time = self.parse_time(
            timing.get("start_time"),
            "timing.start_time",
        )
        end_time = self.parse_time(
            timing.get("end_time"),
            "timing.end_time",
        )
        start = self.local_datetime(start_date, start_time)
        end = self.local_datetime(end_date, end_time)

        if end <= start:
            raise ValueError("Event end must be after event start")

        return {
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": LOCAL_TIMEZONE,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": LOCAL_TIMEZONE,
            },
        }

    def build_reminders(self, reminder_minutes, all_day):

        if reminder_minutes is None:
            return {
                "useDefault": False,
                "overrides": [],
            }

        if reminder_minutes == "default":
            reminder_minutes = (
                DEFAULT_ALL_DAY_REMINDER_MINUTES
                if all_day
                else DEFAULT_TIMED_REMINDER_MINUTES
            )

        if (
            isinstance(reminder_minutes, bool)
            or not isinstance(reminder_minutes, int)
            or reminder_minutes < 0
        ):
            raise ValueError(
                "reminder_minutes must be a non-negative integer or null"
            )

        return {
            "useDefault": False,
            "overrides": [
                {
                    "method": "popup",
                    "minutes": reminder_minutes,
                }
            ],
        }

    def create_event(
        self,
        summary,
        timing,
        location=None,
        description=None,
        reminder_minutes="default",
    ):

        summary = str(summary).strip()

        if not summary:
            raise ValueError("summary must not be empty")

        timing_body = self.build_timing(timing)
        all_day = bool(timing["all_day"])
        body = {
            "summary": summary,
            **timing_body,
            "reminders": self.build_reminders(
                reminder_minutes,
                all_day,
            ),
        }

        if location is not None:
            body["location"] = str(location)

        if description is not None:
            body["description"] = str(description)

        created = (
            self.get_service()
            .events()
            .insert(calendarId="primary", body=body)
            .execute()
        )

        return {"event": self.normalize_event(created)}
