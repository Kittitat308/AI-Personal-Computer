import asyncio
import contextlib
import json
import sys
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from config import (
    BROWSER_BRIDGE_HOST,
    BROWSER_BRIDGE_PORT,
    MCP_HOST,
    MCP_PORT,
    YOUTUBE_API_KEY,
)
from youtube import YouTubeService


YOUTUBE = YouTubeService(YOUTUBE_API_KEY)
SERVER = MCPServer(
    name="youtube",
    instructions=(
        "Use these tools to search YouTube through the YouTube Data API and "
        "open a selected video through the managed browser."
    ),
)


async def call_browser_bridge(request: dict) -> dict:
    reader, writer = await asyncio.open_connection(
        BROWSER_BRIDGE_HOST,
        BROWSER_BRIDGE_PORT,
    )

    try:
        writer.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        raw_response = await asyncio.wait_for(reader.readline(), timeout=35)
    finally:
        writer.close()
        await writer.wait_closed()

    if not raw_response:
        raise RuntimeError("Managed browser connection closed unexpectedly")

    response = json.loads(raw_response.decode("utf-8"))

    if not response.get("ok"):
        raise RuntimeError(response.get("error") or "Browser could not open the video")

    return response["result"]


@SERVER.tool(description="Search YouTube for videos or channels through the YouTube Data API.")
async def search_youtube(
    query: Annotated[str, Field(min_length=1)],
    resource_type: Literal["video", "channel"] = "video",
    order: Literal["relevance", "date", "view_count"] = "relevance",
    max_results: Annotated[int, Field(ge=1, le=10)] = 5,
) -> dict:
    return await asyncio.to_thread(
        YOUTUBE.search,
        query=query,
        resource_type=resource_type,
        order=order,
        max_results=max_results,
    )


@SERVER.tool(
    description=(
        "Open a YouTube video by its 11-character video ID. Open it in a new "
        "tab, or replace an explicitly specified existing YouTube tab."
    )
)
async def open_video(
    video_id: Annotated[
        str,
        Field(min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$"),
    ],
    open_mode: Literal["new_tab", "specified_tab"] = "new_tab",
    tab_id: str = "",
) -> dict:
    url = YOUTUBE.video_url(video_id)

    if open_mode == "specified_tab" and not tab_id.strip():
        raise ValueError("tab_id is required when open_mode is specified_tab")

    return await call_browser_bridge(
        {
            "action": "open_youtube_video",
            "url": url,
            "open_mode": open_mode,
            "tab_id": tab_id.strip(),
        }
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
