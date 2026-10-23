---
name: youtube
description: Search for videos or channels through the YouTube Data API and open a selected YouTube video in a new tab or a specified existing YouTube tab.
---

# YouTube

## Instructions

- Use `search_youtube` to search for a video or channel. Search only for the
  resource type the user requests.
- Keep `order` as `relevance` unless the user explicitly requests newest or
  most-viewed results.
- Use `open_video` only with a `video_id` returned by `search_youtube` or
  explicitly supplied by the user.
- To open a channel, use the Browser skill's `open_website` with the channel
  URL returned by `search_youtube`.
- If several relevant channels match and the user did not identify one more
  precisely, select the matching result with the highest visible subscriber
  count. If several relevant videos match under the same conditions, select
  the matching result with the highest view count. Compare only results
  returned by the tool and do not claim they are the highest across YouTube.
- If subscriber counts are hidden or the available statistics do not identify
  a clear result, ask one concise clarification question instead of guessing.
- Use `new_tab` unless the user explicitly asks to reuse a particular existing
  YouTube tab.
- Before using `specified_tab`, use the Browser skill to list open websites and
  obtain the exact `tab_id`. Never guess a tab ID.
- Use `specified_tab` only for a tab confirmed to be a YouTube tab. If the
  requested tab is unclear, ask one concise question before opening the video.
- Do not invent search results, IDs, titles, channel names, or publication
  times. Base the result only on tool output.

## Response

- After successfully opening a channel or video, respond with exactly one
  short spoken sentence that states only what was opened.
- Do not include search-result details, descriptions, subscriber counts, view
  counts, publication information, selection reasoning, alternative results,
  or optional follow-up offers.
- If the requested action fails or requires clarification, state only the
  useful reason or ask one concise question.

## Available tools

- `search_youtube`
- `open_video`
