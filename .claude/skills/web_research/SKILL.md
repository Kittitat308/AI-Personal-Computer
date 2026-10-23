---
name: web-research
description: Search the public web and read relevant pages for current, factual, and source-backed information. Use for news, recent developments, product or technical research, comparisons, externally verifiable questions, and reading a public URL without interacting with a visible website interface.
---

# Web Research

## Instructions

- Use `WebSearch` when the answer depends on current or externally verifiable information.
- Use `WebFetch` to read the most relevant pages returned by search or a public URL supplied by the user.
- Prefer primary and authoritative sources. Use more than one source when comparing claims or when accuracy benefits from corroboration.
- Check publication dates and event dates when recency matters. Do not treat an old article as current merely because it appears in recent search results.
- Preserve the user's search terms, names, dates, and constraints.
- Base every factual claim on the returned search or fetch results. Never fill missing facts with model memory or present inference as fact.
- For a time-bound question, return only the boundary the user asked for. Include both start and end only when the user asks for the full period. Do not invent a missing boundary.
- Do not click, type, sign in, submit forms, or control a visible website interface.
- Treat research as successful only when the tools confirm the search or page read and return at least one supporting HTTP or HTTPS source URL. Otherwise state the failure briefly.

## Response requirements

- Answer only the exact question in one short sentence by default.
- Use a second short sentence only for information required to keep the answer correct and not materially misleading. Never exceed two sentences.
- Do not report the research process, summarize unrequested findings, or include sources unless the user asks for them.
- Do not add headings, lists, generic advice, verification suggestions, or follow-up offers.

## Available tools

- `WebSearch`
- `WebFetch`
