"""User mark changes preserve independent fields and stable acknowledgment times."""

from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.mark_transitions import (
    mark_favorite,
    mark_position,
    mark_seen,
)

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(days=1)
LATER = NOW + timedelta(days=1)


def test_seen_acknowledges_new_content_and_future_imports() -> None:
    previous = PostMarks(
        seen_at=EARLIER, favorite=True, positions={'audio': PlaybackPosition(4.5)}
    )
    result = mark_seen(previous, seen=True, now=NOW, latest_added_at=LATER)
    assert result.seen_at == LATER
    assert result.favorite
    result.positions['audio'].seconds = 99
    assert previous.positions['audio'].seconds == 4.5
    assert previous.seen_at == EARLIER


def test_seen_noop_preserves_timestamp_and_clearing_preserves_other_fields() -> None:
    previous = PostMarks(
        seen_at=NOW, favorite=True, positions={'audio': PlaybackPosition(4.5)}
    )
    assert (
        mark_seen(previous, seen=True, now=LATER, latest_added_at=EARLIER) == previous
    )
    cleared = mark_seen(previous, seen=False, now=LATER, latest_added_at=LATER)
    assert cleared == PostMarks(
        seen_at=None, favorite=True, positions={'audio': PlaybackPosition(4.5)}
    )
    assert previous.seen_at == NOW


def test_favorite_changes_only_its_field() -> None:
    previous = PostMarks(
        seen_at=NOW, favorite=False, positions={'audio': PlaybackPosition(4.5)}
    )
    result = mark_favorite(previous, favorite=True)
    assert result == PostMarks(
        seen_at=NOW, favorite=True, positions={'audio': PlaybackPosition(4.5)}
    )
    result.positions['audio'].seconds = 99
    assert previous.positions['audio'].seconds == 4.5
    assert not previous.favorite


@pytest.mark.parametrize(
    ('duration', 'before', 'boundary'),
    [(24.0, 22.799, 22.8), (3600.0, 3589.999, 3590.0)],
)
def test_short_and_long_completion_windows(
    duration: float, before: float, boundary: float
) -> None:
    marks = PostMarks(seen_at=EARLIER, favorite=True)
    partial = mark_position(marks, 'video', before, duration, now=NOW)
    assert partial.positions['video'] == PlaybackPosition(before)
    finished = mark_position(partial, 'video', boundary, duration, now=NOW)
    assert finished.positions['video'] == PlaybackPosition(0.0, NOW)
    assert finished.seen_at == EARLIER
    assert finished.favorite


def test_repeated_completion_is_stable_and_replay_clears_finished() -> None:
    marks = PostMarks(positions={'video': PlaybackPosition(0.0, EARLIER)})
    assert mark_position(marks, 'video', 120, 90, now=NOW) == marks
    result = mark_position(marks, 'video', 0.5, 90, now=NOW)
    assert result.positions['video'] == PlaybackPosition(0.5)
    assert marks.positions['video'].finished_at == EARLIER


def test_unknown_duration_never_marks_finished() -> None:
    result = mark_position(PostMarks(), 'video', 150, 0, now=NOW)
    assert result.positions['video'] == PlaybackPosition(150)


@pytest.mark.parametrize('bad', [True, -1.0, float('nan'), float('inf'), float('-inf')])
@pytest.mark.parametrize('field', ['seconds', 'duration'])
def test_invalid_numeric_values_never_mutate_marks(bad: float, field: str) -> None:
    marks = PostMarks(positions={'video': PlaybackPosition(12)})
    arguments = {'seconds': 15.0, 'duration': 90.0, field: bad}
    with pytest.raises(ValueError, match='finite and nonnegative'):
        mark_position(marks, 'video', now=NOW, **arguments)
    assert marks.positions['video'] == PlaybackPosition(12)
