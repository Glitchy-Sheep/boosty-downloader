"""
User-owned viewing marks, separate from downloaded post content.

Datetimes are timezone-aware UTC values. Storage adapters and viewer input handling validate these mutable persisted values.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PlaybackPosition:
    """Playback progress in finite, nonnegative seconds; no finish time means unfinished."""

    seconds: float = 0.0
    finished_at: datetime | None = None


@dataclass
class PostMarks:
    """User marks and playback positions keyed by media ID within this post."""

    seen_at: datetime | None = None
    favorite: bool = False
    positions: dict[str, PlaybackPosition] = field(
        default_factory=dict[str, PlaybackPosition]
    )
