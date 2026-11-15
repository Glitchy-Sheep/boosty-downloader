"""Pure mark snapshots share strict JSON validation without a storage envelope."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from traceback import format_exception
from typing import cast

import pytest

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.infrastructure.library._marks_validation import (
    validate_marks_snapshot,
)
from boosty_downloader.infrastructure.library.errors import InvalidViewerRecordError

NOW = datetime(2026, 11, 15, 12, 34, 56, 123456, tzinfo=timezone.utc)


def test_integer_seconds_and_offset_dates_create_independent_utc_snapshots():
    local_time = NOW.astimezone(timezone(timedelta(hours=3)))
    marks = PostMarks(
        seen_at=local_time, positions={'future:piece': PlaybackPosition(42, local_time)}
    )
    expected = deepcopy(marks)
    snapshot = validate_marks_snapshot(marks)
    assert snapshot == expected
    assert snapshot.seen_at is not None
    assert snapshot.seen_at.tzinfo is timezone.utc
    finished = snapshot.positions['future:piece'].finished_at
    assert finished is not None
    assert finished.tzinfo is timezone.utc
    snapshot.positions['future:piece'].seconds = 100
    snapshot.positions.clear()
    assert marks == expected
    assert marks.seen_at is local_time


@pytest.mark.parametrize('seconds', [True, -1, float('nan'), float('inf'), '42'])
def test_snapshot_rejects_invalid_seconds_without_leaking_media_identity(
    seconds: object,
):
    private_key = 'external_video:https://example.com/watch?token=private-key'
    marks = PostMarks(positions={private_key: PlaybackPosition(cast('float', seconds))})
    with pytest.raises(InvalidViewerRecordError) as raised:
        validate_marks_snapshot(marks)
    assert private_key not in ''.join(format_exception(raised.value))


@pytest.mark.parametrize('favorite', [1, 'true', None])
def test_snapshot_requires_an_actual_boolean(favorite: object):
    marks = PostMarks(favorite=cast('bool', favorite))
    with pytest.raises(InvalidViewerRecordError, match='favorite'):
        validate_marks_snapshot(marks)
