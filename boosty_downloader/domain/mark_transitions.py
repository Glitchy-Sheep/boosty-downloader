"""Pure user-mark transitions with explicit observation time."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import TYPE_CHECKING, Final

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks

if TYPE_CHECKING:
    from datetime import datetime

_FINISH_WINDOW_SECONDS: Final = 10.0
_FINISH_WINDOW_FRACTION: Final = 0.05


def mark_seen(
    marks: PostMarks, *, seen: bool, now: datetime, latest_added_at: datetime | None
) -> PostMarks:
    """Acknowledge current content without replacing a still-current seen mark."""
    result = deepcopy(marks)
    if not seen:
        result.seen_at = None
    elif marks.seen_at is None or (
        latest_added_at is not None and latest_added_at > marks.seen_at
    ):
        # Imported future timestamps are acknowledged without changing content history.
        result.seen_at = max(now, latest_added_at or now)
    return result


def mark_favorite(marks: PostMarks, *, favorite: bool) -> PostMarks:
    """Change only the favorite value, retaining independent playback positions."""
    result = deepcopy(marks)
    result.favorite = favorite
    return result


def mark_position(
    marks: PostMarks,
    media_id: str,
    seconds: float,
    duration: float,
    *,
    now: datetime,
) -> PostMarks:
    """Retain partial playback, or start completed pieces from zero next time."""
    _validate_seconds(seconds)
    _validate_seconds(duration)
    result = deepcopy(marks)
    previous = result.positions.get(media_id)
    window = min(_FINISH_WINDOW_SECONDS, duration * _FINISH_WINDOW_FRACTION)
    if duration > 0 and seconds >= duration - window:
        finished_at = previous.finished_at if previous is not None else None
        result.positions[media_id] = PlaybackPosition(0.0, finished_at or now)
    else:
        result.positions[media_id] = PlaybackPosition(seconds)
    return result


def _validate_seconds(value: float) -> None:
    if isinstance(value, bool) or not isfinite(value) or value < 0:
        message = 'Playback seconds must be finite and nonnegative'
        raise ValueError(message)
