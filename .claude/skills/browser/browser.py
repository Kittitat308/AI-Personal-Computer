import asyncio
import contextlib
from urllib.parse import quote_plus, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from config import BROWSER_ARGUMENTS, HEADLESS, USER_DATA_DIR


class BrowserController:
    def __init__(self):
        self.playwright = None
        self.context = None
        self.tab_ids = {}
        self.next_tab_number = 1
        self.lifecycle_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self.lifecycle_lock:
            if self._context_is_usable():
                return

            await self._close_runtime()
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.playwright = await async_playwright().start()

            try:
                context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=str(USER_DATA_DIR),
                    headless=HEADLESS,
                    args=BROWSER_ARGUMENTS,
                    no_viewport=True,
                )
            except Exception:
                await self.playwright.stop()
                self.playwright = None
                raise

            self.context = context
            context.on("close", self._on_context_closed)

            for page in context.pages:
                self._tab_id(page)

    def _context_is_usable(self) -> bool:
        if self.context is None:
            return False

        try:
            browser = self.context.browser
            return browser is not None and browser.is_connected()
        except Exception:
            return False

    def _on_context_closed(self, context) -> None:
        if self.context is context:
            self.context = None
            self._reset_tab_state()

    def _reset_tab_state(self) -> None:
        self.tab_ids = {}
        self.next_tab_number = 1

    def _tab_id(self, page) -> str:
        page_key = id(page)

        if page_key not in self.tab_ids:
            self.tab_ids[page_key] = f"tab-{self.next_tab_number}"
            self.next_tab_number += 1

        return self.tab_ids[page_key]

    async def _pages(self):
        await self.start()
        pages = [page for page in self.context.pages if not page.is_closed()]

        for page in pages:
            self._tab_id(page)

        return pages

    def _validate_url(self, url: str) -> str:
        if not isinstance(url, str):
            raise ValueError("URL must be a string")

        url = url.strip()
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Only valid HTTP and HTTPS URLs are allowed")

        return url

    async def _replace_blank_page(self, page, url: str) -> None:
        async with page.expect_navigation(
            wait_until="domcontentloaded",
            timeout=30000,
        ):
            await page.evaluate("target => window.location.replace(target)", url)

    async def _close_unused_blank_tabs(self, keep_page) -> None:
        for page in list(self.context.pages):
            if page is keep_page or page.is_closed():
                continue

            if page.url == "about:blank":
                await page.close()

    async def open_website(self, url: str) -> dict:
        url = self._validate_url(url)

        try:
            return await self._open_website(url)
        except PlaywrightError as error:
            if not self._browser_was_closed(error):
                raise

            await self.close()
            return await self._open_website(url)

    @staticmethod
    def _browser_was_closed(error: PlaywrightError) -> bool:
        message = str(error).casefold()
        return (
            "has been closed" in message
            and any(word in message for word in ("page", "context", "browser"))
        )

    async def _open_website(self, url: str) -> dict:
        await self.start()
        page = await self.context.new_page()

        try:
            await self._replace_blank_page(page, url)
        except Exception:
            with contextlib.suppress(Exception):
                await page.close()
            raise

        await self._close_unused_blank_tabs(page)
        await page.bring_to_front()
        return await self._tab_data(page)

    async def search_web(self, query: str) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must not be blank")

        return await self.open_website(
            "https://www.google.com/search?q=" + quote_plus(query.strip())
        )

    async def open_in_tab(self, url: str, tab_id: str) -> dict:
        url = self._validate_url(url)

        if not isinstance(tab_id, str) or not tab_id.strip():
            raise ValueError("Tab ID must be a non-empty string")

        pages = await self._pages()
        pages_by_id = {self._tab_id(page): page for page in pages}
        normalized_id = tab_id.strip()
        page = pages_by_id.get(normalized_id)

        if page is None:
            raise ValueError(f"Unknown tab ID: {normalized_id}")

        current_host = (urlparse(page.url).hostname or "").casefold()

        if current_host != "youtube.com" and not current_host.endswith(".youtube.com"):
            raise ValueError(f"Tab {normalized_id} is not a YouTube tab")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.bring_to_front()
        return await self._tab_data(page)

    async def _tab_data(self, page) -> dict:
        try:
            title = await page.title()
        except Exception:
            title = ""

        return {
            "tab_id": self._tab_id(page),
            "url": page.url,
            "title": title,
        }

    async def get_open_websites(self) -> dict:
        if self.context is None:
            return {"websites": []}

        if not self._context_is_usable():
            await self.close()
            return {"websites": []}

        websites = []

        for page in self.context.pages:
            if page.is_closed():
                continue

            data = await self._tab_data(page)

            if urlparse(data["url"]).scheme not in {"http", "https"}:
                continue

            websites.append(data)

        return {"websites": websites}

    async def close_tabs(self, tab_ids: list[str]) -> dict:
        if not isinstance(tab_ids, list) or not tab_ids:
            raise ValueError("At least one tab ID is required")

        requested_ids = []

        for tab_id in tab_ids:
            if not isinstance(tab_id, str) or not tab_id.strip():
                raise ValueError("Tab IDs must be non-empty strings")

            normalized_id = tab_id.strip()
            if normalized_id not in requested_ids:
                requested_ids.append(normalized_id)

        pages_by_id = {
            self._tab_id(page): page
            for page in await self._pages()
        }
        missing_ids = [
            tab_id for tab_id in requested_ids if tab_id not in pages_by_id
        ]

        if missing_ids:
            raise ValueError("Unknown tab IDs: " + ", ".join(missing_ids))

        closed_tabs = []

        for tab_id in requested_ids:
            page = pages_by_id[tab_id]
            closed_tabs.append(await self._tab_data(page))
            await page.close()
            self.tab_ids.pop(id(page), None)

        return {"closed_tabs": closed_tabs}

    async def close_browser(self) -> dict:
        was_open = self.context is not None
        await self.close()
        return {"closed": was_open}

    async def close(self) -> None:
        async with self.lifecycle_lock:
            await self._close_runtime()

    async def _close_runtime(self) -> None:
        context = self.context
        playwright = self.playwright
        self.context = None
        self.playwright = None
        self._reset_tab_state()

        if context is not None:
            with contextlib.suppress(Exception):
                await context.close()

        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()
