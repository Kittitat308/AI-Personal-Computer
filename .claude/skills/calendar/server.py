import asyncio
import contextlib
import sys
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from calendar_service import CalendarService
from config import MCP_HOST, MCP_PORT, PROJECT_ROOT, SKILL_DIR


DateValue = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
OptionalDateValue = Annotated[
    str,
    Field(pattern=r"^(?:\d{4}-\d{2}-\d{2})?$"),
]
TimeValue = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
OptionalTimeValue = Annotated[
    str,
    Field(pattern=r"^(?:(?:[01]\d|2[0-3]):[0-5]\d)?$"),
]
ReminderMinutes = Annotated[
    int,
    Field(
        ge=0,
        description=(
            "Popup reminder lead time in minutes. Omit to use the system "
            "default; use null only when the user explicitly requests no reminder."
        ),
    ),
]
DateScope = Literal[
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
]
Weekday = Literal[
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


class AllDayTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_day: Literal[True]
    start_date: DateValue
    end_date: DateValue


class TimedTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_day: Literal[False]
    start_date: DateValue
    start_time: TimeValue
    end_date: DateValue
    end_time: TimeValue


CALENDAR = CalendarService(
    project_root=PROJECT_ROOT,
    skill_directory=SKILL_DIR,
)
SERVER = MCPServer(
    name="calendar",
    instructions=(
        "Use these tools only to read events from or create events in the "
        "user's primary Google Calendar."
    ),
)


@SERVER.tool(
    description=(
        "Read events from the primary Google Calendar. Dates and times use "
        "Asia/Bangkok. Custom start_date is inclusive and end_date is exclusive."
    )
)
async def read_events(
    date_scope: DateScope = "upcoming",
    start_date: OptionalDateValue = "",
    end_date: OptionalDateValue = "",
    weekdays: list[Weekday] | None = None,
    start_time: OptionalTimeValue = "",
    end_time: OptionalTimeValue = "",
) -> dict:
    return await asyncio.to_thread(
        CALENDAR.read_events,
        date_scope=date_scope,
        start_date=start_date,
        end_date=end_date,
        weekdays=weekdays or [],
        start_time=start_time,
        end_time=end_time,
    )


@SERVER.tool(description="Create one event in the primary Google Calendar.")
async def create_event(
    summary: Annotated[str, Field(min_length=1)],
    timing: AllDayTiming | TimedTiming,
    location: str | None = None,
    description: str | None = None,
    reminder_minutes: ReminderMinutes | None | Literal["default"] = "default",
) -> dict:
    return await asyncio.to_thread(
        CALENDAR.create_event,
        summary=summary,
        timing=timing.model_dump(),
        location=location,
        description=description,
        reminder_minutes=reminder_minutes,
    )


async def wait_for_shutdown() -> None:
    await asyncio.to_thread(sys.stdin.buffer.readline)


async def main() -> None:
    server_task = asyncio.create_task(
        SERVER.run_streamable_http_async(
            host=MCP_HOST,
            port=MCP_PORT,
            streamable_http_path="/mcp",
        )
    )
    shutdown_task = asyncio.create_task(wait_for_shutdown())

    done, _ = await asyncio.wait(
        {server_task, shutdown_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if shutdown_task in done:
        server_task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await server_task
    else:
        shutdown_task.cancel()
        await server_task


if __name__ == "__main__":
    asyncio.run(main())
