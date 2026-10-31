import asyncio
import contextlib
import json
import sys

from mcp.server.mcpserver import MCPServer

from browser import BrowserController
from config import BROWSER_BRIDGE_HOST, BROWSER_BRIDGE_PORT, MCP_HOST, MCP_PORT


BROWSER = BrowserController()
SERVER = MCPServer(
    name="browser",
    instructions=(
        "Use these tools only for opening websites, visible web searches, "
        "listing managed websites, closing matching website tabs, and closing "
        "the managed browser."
    ),
)


@SERVER.tool(description="Open an HTTP or HTTPS URL in a new browser tab.")
async def open_website(url: str) -> dict:
    return await BROWSER.open_website(url)


@SERVER.tool(description="Open a Google web search for a query in a new browser tab.")
async def search_web(query: str) -> dict:
    return await BROWSER.search_web(query)


async def open_youtube_video(url: str, open_mode: str, tab_id: str) -> dict:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()

    if parsed.scheme != "https" or (
        host != "youtube.com" and not host.endswith(".youtube.com")
    ) or parsed.path != "/watch":
        raise ValueError("Only HTTPS YouTube watch URLs are allowed")

    if open_mode == "new_tab":
        return await BROWSER.open_website(url)

    if open_mode == "specified_tab":
        return await BROWSER.open_in_tab(url, tab_id)

    raise ValueError("open_mode must be new_tab or specified_tab")


async def handle_browser_bridge(reader, writer) -> None:
    try:
        raw_request = await asyncio.wait_for(reader.readline(), timeout=10)
        request = json.loads(raw_request.decode("utf-8"))

        if request.get("action") != "open_youtube_video":
            raise ValueError("Unsupported browser bridge action")

        result = await open_youtube_video(
            request.get("url", ""),
            request.get("open_mode", "new_tab"),
            request.get("tab_id", ""),
        )
        response = {"ok": True, "result": result}
    except Exception as error:
        response = {"ok": False, "error": str(error)}

    writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


@SERVER.tool(description="Close one or more managed browser tabs by exact tab ID.")
async def close_tabs(tab_ids: list[str]) -> dict:
    return await BROWSER.close_tabs(tab_ids)


@SERVER.tool(
    description=(
        "List managed HTTP and HTTPS tabs from left to right with tab ID, URL, "
        "and title."
    )
)
async def get_open_websites() -> dict:
    return await BROWSER.get_open_websites()


@SERVER.tool(description="Close the managed browser session and all of its tabs.")
async def close_browser() -> dict:
    return await BROWSER.close_browser()


async def wait_for_shutdown() -> None:
    await asyncio.to_thread(sys.stdin.buffer.readline)


async def main() -> None:
    bridge_server = await asyncio.start_server(
        handle_browser_bridge,
        host=BROWSER_BRIDGE_HOST,
        port=BROWSER_BRIDGE_PORT,
    )
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
        await BROWSER.close()
        bridge_server.close()
        await bridge_server.wait_closed()
        server_task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await server_task
    else:
        bridge_server.close()
        await bridge_server.wait_closed()
        shutdown_task.cancel()
        await server_task


if __name__ == "__main__":
    asyncio.run(main())
