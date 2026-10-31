import asyncio
import contextlib
import sys
from typing import Literal

from mcp.server.mcpserver import MCPServer

from config import MCP_HOST, MCP_PORT, PROJECT_ROOT, TOKEN_PATH
from reader import GmailReader


READER = GmailReader(
    project_root=PROJECT_ROOT,
    token_path=TOKEN_PATH,
)
SERVER = MCPServer(
    name="gmail",
    instructions=(
        "Use this read-only tool to retrieve messages from the user's Gmail "
        "Inbox. Never modify or send email."
    ),
)


@SERVER.tool(
    description=(
        "Filter and read Inbox messages through the read-only Gmail API. "
        "Dates use Asia/Bangkok local calendar boundaries; start_date is "
        "inclusive and end_date is exclusive."
    )
)
async def read_emails(
    start_date: str = "",
    end_date: str = "",
    read_status: Literal["all", "read", "unread"] = "all",
    max_results: int = 10,
    content_level: Literal["metadata", "full"] = "metadata",
    sender_email: str = "",
) -> dict:
    return await asyncio.to_thread(
        READER.read_emails,
        start_date=start_date,
        end_date=end_date,
        read_status=read_status,
        max_results=max_results,
        content_level=content_level,
        sender_email=sender_email,
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

