import re
from datetime import datetime
from html import unescape
from zoneinfo import ZoneInfo

import requests


SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
BANGKOK_TIMEZONE = ZoneInfo("Asia/Bangkok")


class YouTubeService:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(
        self,
        query: str,
        resource_type: str = "video",
        order: str = "relevance",
        max_results: int = 5,
    ) -> dict:
        query = query.strip() if isinstance(query, str) else ""

        if not query:
            raise ValueError("Search query must not be blank")

        if resource_type not in {"video", "channel"}:
            raise ValueError("resource_type must be video or channel")

        order_map = {
            "relevance": "relevance",
            "date": "date",
            "view_count": "viewCount",
        }

        if order not in order_map:
            raise ValueError("order must be relevance, date, or view_count")

        if not isinstance(max_results, int) or not 1 <= max_results <= 10:
            raise ValueError("max_results must be between 1 and 10")

        if not self.api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not configured")

        response = requests.get(
            SEARCH_URL,
            params={
                "part": "snippet",
                "q": query,
                "type": resource_type,
                "order": order_map[order],
                "maxResults": max_results,
                "regionCode": "TH",
                "relevanceLanguage": "th",
                "safeSearch": "moderate",
                "key": self.api_key,
            },
            timeout=15,
        )

        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError("YouTube API returned an invalid response") from error

        if not response.ok:
            details = payload.get("error", {}).get("message", "Unknown YouTube API error")
            raise RuntimeError(f"YouTube API request failed: {details}")

        items = payload.get("items", [])[:max_results]
        resource_ids = [
            item.get("id", {}).get(
                "videoId" if resource_type == "video" else "channelId",
                "",
            )
            for item in items
        ]
        statistics = self._get_statistics(resource_type, resource_ids)
        results = [self._format_item(item, resource_type, statistics) for item in items]
        return {
            "query": query,
            "resource_type": resource_type,
            "order": order,
            "returned_count": len(results),
            "results": results,
        }

    def _get_statistics(self, resource_type: str, resource_ids: list[str]) -> dict:
        resource_ids = [resource_id for resource_id in resource_ids if resource_id]

        if not resource_ids:
            return {}

        response = requests.get(
            VIDEOS_URL if resource_type == "video" else CHANNELS_URL,
            params={
                "part": "statistics",
                "id": ",".join(resource_ids),
                "key": self.api_key,
            },
            timeout=15,
        )

        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError("YouTube API returned invalid statistics") from error

        if not response.ok:
            details = payload.get("error", {}).get("message", "Unknown YouTube API error")
            raise RuntimeError(f"YouTube statistics request failed: {details}")

        return {
            item.get("id", ""): item.get("statistics", {})
            for item in payload.get("items", [])
        }

    def _format_item(
        self,
        item: dict,
        resource_type: str,
        statistics: dict,
    ) -> dict:
        snippet = item.get("snippet", {})
        published_at = self._bangkok_time(snippet.get("publishedAt", ""))

        if resource_type == "video":
            video_id = item.get("id", {}).get("videoId", "")
            video_statistics = statistics.get(video_id, {})
            return {
                "resource_type": "video",
                "video_id": video_id,
                "video_title": unescape(snippet.get("title", "")),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": unescape(snippet.get("channelTitle", "")),
                "published_at": published_at,
                "view_count": self._integer_or_none(video_statistics.get("viewCount")),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }

        channel_id = item.get("id", {}).get("channelId", "")
        channel_statistics = statistics.get(channel_id, {})
        return {
            "resource_type": "channel",
            "channel_id": channel_id,
            "channel_title": unescape(
                snippet.get("channelTitle") or snippet.get("title", "")
            ),
            "description": unescape(snippet.get("description", "")),
            "published_at": published_at,
            "subscriber_count": self._integer_or_none(
                channel_statistics.get("subscriberCount")
            ),
            "subscriber_count_hidden": bool(
                channel_statistics.get("hiddenSubscriberCount", False)
            ),
            "url": f"https://www.youtube.com/channel/{channel_id}",
        }

    @staticmethod
    def _integer_or_none(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bangkok_time(value: str) -> str:
        if not value:
            return ""

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

        return parsed.astimezone(BANGKOK_TIMEZONE).isoformat(timespec="seconds")

    @staticmethod
    def video_url(video_id: str) -> str:
        video_id = video_id.strip() if isinstance(video_id, str) else ""

        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            raise ValueError("video_id must be an 11-character YouTube video ID")

        return f"https://www.youtube.com/watch?v={video_id}"
