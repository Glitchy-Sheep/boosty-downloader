"""The module provides tools to work with ok video links (selecting them) by quality."""

from __future__ import annotations

import heapq
from typing import Generic, TypeVar

from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
    BoostyOkVideoUrl,
)

KT = TypeVar('KT')


class RankingDict(Generic[KT]):
    """A dict which also keeps track of the max value, it's not thread-safe"""

    def __init__(self) -> None:
        self.data: dict[KT, float] = {}
        self.max_heap: list[tuple[float, KT]] = []
        self.entries: dict[KT, tuple[float, KT]] = {}

    def __getitem__(self, key: KT) -> float:
        """Get the value associated with the key"""
        return self.data[key]

    def __setitem__(self, key: KT, value: float) -> None:
        """Set the value associated with the key"""
        self.data[key] = value
        entry = (-value, key)
        self.entries[key] = entry
        heapq.heappush(self.max_heap, entry)

    def __delitem__(self, key: KT) -> None:
        """Remove the key and its value"""
        if key in self.data:
            del self.data[key]
        if key in self.entries:
            self.entries[key] = (float('-inf'), key)  # Mark as deleted

    def pop_max(self) -> tuple[KT, float] | None:
        """Pop the maximum value"""
        while self.max_heap:
            value, key = heapq.heappop(self.max_heap)
            if key in self.data and self.entries[key] == (value, key):
                del self.data[key]
                del self.entries[key]
                return key, -value  # Convert back to positive
        return None


def get_quality_ranking() -> RankingDict[BoostyOkVideoType]:
    """Get the ranking dict for video quality"""
    quality_ranking = RankingDict[BoostyOkVideoType]()
    quality_ranking[BoostyOkVideoType.ultra_hd] = 17
    quality_ranking[BoostyOkVideoType.quad_hd] = 16
    quality_ranking[BoostyOkVideoType.full_hd] = 15
    quality_ranking[BoostyOkVideoType.high] = 14
    quality_ranking[BoostyOkVideoType.medium] = 13
    quality_ranking[BoostyOkVideoType.low] = 12
    quality_ranking[BoostyOkVideoType.tiny] = 11
    quality_ranking[BoostyOkVideoType.lowest] = 10
    quality_ranking[BoostyOkVideoType.live_playback_dash] = 9
    quality_ranking[BoostyOkVideoType.live_playback_hls] = 8
    quality_ranking[BoostyOkVideoType.live_ondemand_hls] = 7
    quality_ranking[BoostyOkVideoType.live_dash] = 6
    quality_ranking[BoostyOkVideoType.live_hls] = 5
    quality_ranking[BoostyOkVideoType.hls] = 4
    quality_ranking[BoostyOkVideoType.dash] = 3
    quality_ranking[BoostyOkVideoType.dash_uni] = 2
    quality_ranking[BoostyOkVideoType.live_cmaf] = 1

    return quality_ranking


def get_best_video(
    video_urls: list[BoostyOkVideoUrl],
    preferred_quality: BoostyOkVideoType = BoostyOkVideoType.medium,
) -> tuple[BoostyOkVideoUrl, BoostyOkVideoType] | None:
    """Select the best video format for downloading according to user's preferences"""
    quality_ranking: RankingDict[BoostyOkVideoType] = get_quality_ranking()
    quality_ranking[preferred_quality] = float('inf')

    video_urls_map = {video.type: video for video in video_urls}

    while highest_rank_video_type := quality_ranking.pop_max():
        highest_rank_video_type = highest_rank_video_type[0]

        video_url = video_urls_map.get(highest_rank_video_type)
        if video_url and video_url.url:
            return video_url, highest_rank_video_type

    return None
