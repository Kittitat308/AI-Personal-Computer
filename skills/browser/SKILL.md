---
name: browser
description: Open websites, close matching website tabs or the managed browser, list open websites, and open visible web searches through the local Playwright browser controller.
---

# Browser

## Instructions

- Use this skill only for opening websites, closing matching website tabs or
  the managed browser, listing open websites, and opening visible web searches.
- To open a requested website, call `open_website` with its official HTTP or
  HTTPS URL.
- Use `search_web` when the user asks to search the web through the visible
  browser.
- Never replace or navigate a tab the user already has open when opening
  another website or search.
- Resolve commonly known website names to their official URLs. Ask one concise
  question if the website cannot be identified reliably.
- Before closing tabs, call `get_open_websites` and identify the requested tabs
  from their left-to-right order, tab IDs, URLs, and titles.
- If no open tab clearly matches the request, report that it is not open and do
  not call `close_tabs`.
- If the request clearly identifies one or more tabs, call `close_tabs` once
  with exactly those tab IDs. Never include unrelated tab IDs.
- If multiple tabs match but the user has not made clear whether to close one,
  some, or all of them, ask one concise clarification question before closing
  anything.
- After `close_tabs` confirms which tabs were closed, do not call
  `get_open_websites` again unless the user explicitly asks for the remaining
  open websites.
- Use `get_open_websites` when the user asks which websites are currently open
  or when browser state must be verified before closing a website.
- Use `close_browser` only when the user explicitly asks to close the browser
  itself, not when they ask to close one website.
- Do not click, type into a webpage, submit forms, scroll, navigate an existing
  tab, select search results, or perform any unsupported webpage interaction.
- Do not approximate an unsupported interaction with another tool.
- Use only HTTP and HTTPS websites.
- Report success only after the relevant tool result confirms it.

## Available tools

- `open_website`
- `search_web`
- `close_tabs`
- `get_open_websites`
- `close_browser`
