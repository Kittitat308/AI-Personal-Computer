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
- For a question about when something is valid, starts, ends, or expires, include both boundaries when reliable sources provide them. Do not invent a missing boundary.
- Include a short source list at the end of the response. Give each source's title and complete HTTP or HTTPS URL, and include only sources actually returned by the tools.
- Distinguish sourced facts from inference and identify conflicting or uncertain information explicitly.
- Do not claim that research succeeded unless at least one supporting HTTP or HTTPS source URL was obtained. If reliable sources cannot be obtained, state that clearly and give the reason.
- Do not click, type, sign in, submit forms, or control a visible website interface.
- Do not claim that a search or page read succeeded unless its tool result confirms it.

## Available tools

- `WebSearch`
- `WebFetch`

