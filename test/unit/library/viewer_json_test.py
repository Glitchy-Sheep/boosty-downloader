"""Viewing marks retain user choices and reject invalid or foreign records."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from json import dumps, loads
from traceback import format_exception
from typing import Any, TypeAlias, cast

import pytest

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.infrastructure.library._viewer_json import (
    decode_viewer_record,
    encode_viewer_record,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidViewerRecordError,
    UnsupportedViewerSchemaError,
)

JsonObject: TypeAlias = dict[str, Any]
NOW = datetime(2026, 10, 27, 12, 30, 45, 123456, tzinfo=timezone.utc)
AUTHOR = 'author'
POST_ID = '00000000-0000-4000-8000-000000000001'
OTHER_POST_ID = '00000000-0000-4000-8000-000000000002'
MEDIA_ID = 'boosty_video:Урок 🚀'
DOCUMENT: JsonObject = {
    'schema_version': 1,
    'author': AUTHOR,
    'post_id': POST_ID,
    'marks': {
        'seen_at': '2026-10-27T12:30:45.123456Z',
        'favorite': True,
        'positions': {
            MEDIA_ID: {
                'seconds': 2060.5,
                'finished_at': '2026-10-27T12:30:45.123456Z',
            },
        },
    },
}


def _json_bytes(document: JsonObject) -> bytes:
    return (dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _decode(data: bytes) -> PostMarks:
    return decode_viewer_record(data, author=AUTHOR, post_id=POST_ID)


def _encode(marks: PostMarks) -> bytes:
    return encode_viewer_record(AUTHOR, POST_ID, marks)


@pytest.fixture
def marks() -> PostMarks:
    return PostMarks(
        seen_at=NOW,
        favorite=True,
        positions={MEDIA_ID: PlaybackPosition(2060.5, NOW)},
    )


def test_complete_marks_match_independent_readable_json(marks: PostMarks) -> None:
    expected = _json_bytes(DOCUMENT)

    assert _encode(marks) == expected
    assert _decode(expected) == marks


def test_empty_marks_and_position_defaults_are_explicit() -> None:
    empty = PostMarks()
    assert loads(_encode(empty))['marks'] == {
        'seen_at': None,
        'favorite': False,
        'positions': {},
    }
    assert _decode(_encode(empty)) == empty

    empty.positions[MEDIA_ID] = PlaybackPosition()
    assert loads(_encode(empty))['marks']['positions'][MEDIA_ID] == {
        'seconds': 0.0,
        'finished_at': None,
    }
    assert _decode(_encode(empty)) == empty


def test_nested_snapshots_and_input_are_independent(marks: PostMarks) -> None:
    original = deepcopy(marks)
    encoded = _encode(marks)
    first = _decode(encoded)
    second = _decode(encoded)
    first.positions[MEDIA_ID].seconds = 1.0
    first.positions[MEDIA_ID].finished_at = None
    first.positions.clear()
    first.favorite = False
    marks.positions[MEDIA_ID].seconds = 2.0

    assert second == original
    assert _decode(encoded) == original
    assert marks.favorite is True
    assert marks.positions[MEDIA_ID].finished_at == NOW


def test_dates_normalize_to_utc_without_mutating_inputs(marks: PostMarks) -> None:
    offset = NOW.astimezone(timezone(timedelta(hours=3)))
    marks.seen_at = marks.positions[MEDIA_ID].finished_at = offset
    document = deepcopy(DOCUMENT)
    document['marks']['seen_at'] = offset.isoformat()
    document['marks']['positions'][MEDIA_ID]['finished_at'] = offset.isoformat()

    for restored in (_decode(_encode(marks)), _decode(_json_bytes(document))):
        assert restored == marks
        assert restored.seen_at is not None
        assert restored.seen_at.tzinfo is timezone.utc
        finished_at = restored.positions[MEDIA_ID].finished_at
        assert finished_at is not None
        assert finished_at.tzinfo is timezone.utc
    assert marks.seen_at is offset
    assert marks.positions[MEDIA_ID].finished_at is offset


def test_positions_survive_without_a_current_media_inventory() -> None:
    marks = PostMarks(
        positions={
            'audio:removed-piece': PlaybackPosition(3600.0),
            'future-kind:retained-piece': PlaybackPosition(25.0, NOW),
        }
    )

    assert _decode(_encode(marks)) == marks


@pytest.mark.parametrize('version', [True, '1', 1.0, None])
def test_schema_version_requires_an_exact_integer(version: object) -> None:
    with pytest.raises(InvalidViewerRecordError) as error:
        _decode(_json_bytes({'schema_version': version}))
    assert not isinstance(error.value, UnsupportedViewerSchemaError)


@pytest.mark.parametrize('version', [0, 2])
def test_unsupported_schema_precedes_body_validation(version: int) -> None:
    with pytest.raises(UnsupportedViewerSchemaError):
        _decode(_json_bytes({'schema_version': version, 'future_body': {}}))


@pytest.mark.parametrize('data', [b'{', b'\xff', b'null', b'[]', b'1', b'{}'])
def test_malformed_documents_raise_record_errors(data: bytes) -> None:
    with pytest.raises(InvalidViewerRecordError):
        _decode(data)


@pytest.mark.parametrize('value', [None, [], False])
def test_marks_must_be_an_object(value: object) -> None:
    document = deepcopy(DOCUMENT)
    document['marks'] = value

    with pytest.raises(InvalidViewerRecordError):
        _decode(_json_bytes(document))


@pytest.mark.parametrize(
    ('author', 'post_id'),
    [('other', POST_ID), (AUTHOR, OTHER_POST_ID)],
)
def test_empty_marks_still_validate_full_ownership(author: str, post_id: str) -> None:
    encoded = _encode(PostMarks())

    with pytest.raises(InvalidViewerRecordError):
        decode_viewer_record(encoded, author=author, post_id=post_id)


@pytest.mark.parametrize('field', ['author', 'post_id'])
@pytest.mark.parametrize('value', ['', '   ', True, None])
def test_invalid_identities_fail_on_read_and_write(field: str, value: object) -> None:
    document = deepcopy(DOCUMENT)
    document[field] = value
    identity = {'author': AUTHOR, 'post_id': POST_ID}
    identity[field] = cast('str', value)

    with pytest.raises(InvalidViewerRecordError):
        _decode(_json_bytes(document))
    with pytest.raises(InvalidViewerRecordError):
        encode_viewer_record(identity['author'], identity['post_id'], PostMarks())


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('favorite', 1),
        ('favorite', 'false'),
        ('favorite', None),
        ('positions', []),
        ('positions', None),
        ('positions', {'piece': None}),
        ('positions', {'piece': []}),
    ],
)
def test_invalid_marks_fail_on_read_and_write(
    marks: PostMarks, field: str, value: object
) -> None:
    document = deepcopy(DOCUMENT)
    document['marks'][field] = value
    setattr(marks, field, value)

    with pytest.raises(InvalidViewerRecordError):
        _decode(_json_bytes(document))
    with pytest.raises(InvalidViewerRecordError):
        _encode(marks)


@pytest.mark.parametrize(
    'seconds', [-0.1, True, '20', None, float('nan'), float('inf')]
)
def test_position_requires_finite_nonnegative_seconds(
    marks: PostMarks, seconds: object
) -> None:
    document = deepcopy(DOCUMENT)
    document['marks']['positions'][MEDIA_ID]['seconds'] = seconds
    marks.positions[MEDIA_ID].seconds = cast('float', seconds)

    with pytest.raises(InvalidViewerRecordError):
        _decode(_json_bytes(document))
    with pytest.raises(InvalidViewerRecordError):
        _encode(marks)


@pytest.mark.parametrize('seconds', [0, 2060])
def test_integer_seconds_are_valid_positions(seconds: int) -> None:
    document = deepcopy(DOCUMENT)
    document['marks']['positions'][MEDIA_ID]['seconds'] = seconds

    restored = _decode(_json_bytes(document))

    assert restored.positions[MEDIA_ID].seconds == seconds
    assert _decode(_encode(restored)) == restored


@pytest.mark.parametrize('media_id', ['', '  '])
def test_position_keys_cannot_be_blank(media_id: str) -> None:
    document = deepcopy(DOCUMENT)
    document['marks']['positions'] = {media_id: {'seconds': 0.0, 'finished_at': None}}
    marks = PostMarks(positions={media_id: PlaybackPosition()})

    with pytest.raises(InvalidViewerRecordError):
        _decode(_json_bytes(document))
    with pytest.raises(InvalidViewerRecordError):
        _encode(marks)


@pytest.mark.parametrize('field', ['seen_at', 'finished_at'])
@pytest.mark.parametrize('timestamp', [1700000000, '1700000000', '2026-10-27T12:30:45'])
def test_dates_require_timezone_aware_iso_text(field: str, timestamp: object) -> None:
    document = deepcopy(DOCUMENT)
    target = document['marks']
    if field == 'finished_at':
        target = target['positions'][MEDIA_ID]
    target[field] = timestamp

    with pytest.raises(InvalidViewerRecordError):
        _decode(_json_bytes(document))


@pytest.mark.parametrize('field', ['seen_at', 'finished_at'])
def test_naive_domain_dates_are_rejected(marks: PostMarks, field: str) -> None:
    target: PostMarks | PlaybackPosition = marks
    if field == 'finished_at':
        target = marks.positions[MEDIA_ID]
    setattr(target, field, NOW.replace(tzinfo=None))

    with pytest.raises(InvalidViewerRecordError):
        _encode(marks)


@pytest.mark.parametrize('location', ['record', 'marks', 'position'])
def test_unknown_fields_are_not_silently_lost(location: str) -> None:
    document = deepcopy(DOCUMENT)
    targets = {
        'record': document,
        'marks': document['marks'],
        'position': document['marks']['positions'][MEDIA_ID],
    }
    targets[location]['future_field'] = 'must survive'

    with pytest.raises(InvalidViewerRecordError):
        _decode(_json_bytes(document))


def test_invalid_media_keys_and_values_are_redacted_from_errors() -> None:
    private_key = 'external_video:https://example.com/watch?token=private-media-key'
    private_value = 'private-position-value'
    document = deepcopy(DOCUMENT)
    document['marks']['positions'] = {private_key: {'seconds': private_value}}
    position = PlaybackPosition()
    position.seconds = cast('float', private_value)
    marks = PostMarks(positions={private_key: position})

    for operation in (lambda: _decode(_json_bytes(document)), lambda: _encode(marks)):
        with pytest.raises(InvalidViewerRecordError) as error:
            operation()
        rendered = ''.join(format_exception(error.value))
        assert private_key not in str(error.value)
        assert private_value not in str(error.value)
        assert private_key not in rendered
        assert private_value not in rendered
