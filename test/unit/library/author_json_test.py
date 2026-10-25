"""Author details and locked observations survive independent library reads."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from json import dumps, loads
from traceback import format_exception
from types import MappingProxyType
from typing import Any, TypeAlias

import pytest

from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost, PostMetadata
from boosty_downloader.infrastructure.library._author_json import (
    decode_author_record,
    decode_locked_posts,
    encode_author_record,
    encode_locked_posts,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidAuthorRecordError,
    UnsupportedAuthorSchemaError,
)

JsonObject: TypeAlias = dict[str, Any]
Decoder: TypeAlias = Callable[[bytes], object]
NOW = datetime(2026, 10, 20, 12, 30, 45, 123456, tzinfo=timezone.utc)
POST_ID = 'abcd1234-1111-2222-3333-444444444444'
SECOND_ID = 'abcd1234-1111-2222-3333-555555555555'
AUTHOR_DOCUMENT: JsonObject = {
    'schema_version': 1,
    'author': {
        'author': 'author',
        'synced_at': '2026-10-20T12:30:45.123456Z',
        'title': 'Уроки 🚀',
        'owner_name': 'Автор',
        'description': 'Первый абзац.\n\nВторой абзац.',
        'avatar_path': '.boosty-downloader/avatar.jpg',
        'cover_path': '.boosty-downloader/Обложка.png',
        'remote_post_count': 42,
    },
}
LOCKED_DOCUMENT: JsonObject = {
    'schema_version': 1,
    'author': 'author',
    'posts': {
        POST_ID: {
            'post': {
                'id': POST_ID,
                'author': 'author',
                'url': f'https://boosty.to/author/posts/{POST_ID}',
                'title': 'Закрытый урок 🚀',
                'created_at': '2026-10-20T12:30:45.123456Z',
                'updated_at': '2026-10-20T12:30:45.123456Z',
                'published_at': '2026-10-20T12:30:45.123456Z',
                'tags': ['обучение'],
                'tier': 'Подписка',
                'tier_price_rub': 99.5,
                'post_price_rub': 0.0,
                'likes': 3,
                'comments': 2,
                'content_counters': {'video': 1},
            },
            'synced_at': '2026-10-20T12:30:45.123456Z',
            'teaser_path': f'.boosty-downloader/teasers/{POST_ID}.jpg',
        }
    },
}


def _json_bytes(document: JsonObject) -> bytes:
    return (dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _decode_locked(data: bytes) -> dict[str, LockedPost]:
    return decode_locked_posts(data, author='author')


@pytest.fixture
def author() -> AuthorInfo:
    return AuthorInfo(
        author='author',
        synced_at=NOW,
        title='Уроки 🚀',
        owner_name='Автор',
        description='Первый абзац.\n\nВторой абзац.',
        avatar_path='.boosty-downloader/avatar.jpg',
        cover_path='.boosty-downloader/Обложка.png',
        remote_post_count=42,
    )


@pytest.fixture
def locked() -> LockedPost:
    return LockedPost(
        PostMetadata(
            POST_ID,
            'author',
            f'https://boosty.to/author/posts/{POST_ID}',
            'Закрытый урок 🚀',
            NOW,
            NOW,
            published_at=NOW,
            tags=['обучение'],
            tier='Подписка',
            tier_price_rub=99.5,
            post_price_rub=0.0,
            likes=3,
            comments=2,
            content_counters={'video': 1},
        ),
        NOW,
        f'.boosty-downloader/teasers/{POST_ID}.jpg',
    )


def test_author_matches_independent_readable_json(author: AuthorInfo) -> None:
    expected = _json_bytes(AUTHOR_DOCUMENT)

    assert encode_author_record(author) == expected
    assert decode_author_record(expected) == author


def test_locked_matches_independent_readable_json(locked: LockedPost) -> None:
    expected = _json_bytes(LOCKED_DOCUMENT)

    assert encode_locked_posts('author', {POST_ID: locked}) == expected
    assert _decode_locked(expected) == {POST_ID: locked}


def test_empty_and_optional_fields_are_explicit() -> None:
    author = AuthorInfo('author', NOW)
    document = loads(encode_author_record(author))
    optional_fields = {
        'title',
        'owner_name',
        'description',
        'avatar_path',
        'cover_path',
        'remote_post_count',
    }

    assert all(document['author'][field] is None for field in optional_fields)
    assert decode_author_record(encode_author_record(author)) == author
    assert loads(encode_locked_posts('author', {})) == {
        'schema_version': 1,
        'author': 'author',
        'posts': {},
    }
    assert _decode_locked(encode_locked_posts('author', {})) == {}
    locked = LockedPost(PostMetadata(POST_ID, 'author', '', '', NOW, NOW), NOW)
    encoded = encode_locked_posts('author', {POST_ID: locked})
    assert loads(encoded)['posts'][POST_ID]['teaser_path'] is None
    assert _decode_locked(encoded) == {POST_ID: locked}


def test_full_ids_and_independent_nested_copies_survive(locked: LockedPost) -> None:
    records = {
        POST_ID: locked,
        SECOND_ID: replace(locked, post=replace(locked.post, id=SECOND_ID)),
    }
    original = deepcopy(records)
    encoded = encode_locked_posts('author', records)
    first = _decode_locked(encoded)
    second = _decode_locked(encoded)
    first[POST_ID].post.tags.clear()
    first[POST_ID].post.content_counters.clear()
    first.pop(SECOND_ID)

    assert second == original
    assert records == original
    assert list(second) == [POST_ID, SECOND_ID]


def test_dates_normalize_to_utc_without_mutating_inputs(
    author: AuthorInfo,
    locked: LockedPost,
) -> None:
    offset = NOW.astimezone(timezone(timedelta(hours=3)))
    author.synced_at = locked.synced_at = offset
    locked.post.created_at = locked.post.updated_at = locked.post.published_at = offset
    author_wire = deepcopy(AUTHOR_DOCUMENT)
    author_wire['author']['synced_at'] = offset.isoformat()
    locked_wire = deepcopy(LOCKED_DOCUMENT)
    locked_wire['posts'][POST_ID]['synced_at'] = offset.isoformat()
    for field in ('created_at', 'updated_at', 'published_at'):
        locked_wire['posts'][POST_ID]['post'][field] = offset.isoformat()

    for restored in (
        decode_author_record(encode_author_record(author)),
        decode_author_record(_json_bytes(author_wire)),
    ):
        assert restored.synced_at.tzinfo is timezone.utc
    for posts in (
        _decode_locked(encode_locked_posts('author', {POST_ID: locked})),
        _decode_locked(_json_bytes(locked_wire)),
    ):
        restored_post = posts[POST_ID]
        assert restored_post.synced_at.tzinfo is timezone.utc
        assert restored_post.post.created_at.tzinfo is timezone.utc
        assert restored_post.post.updated_at.tzinfo is timezone.utc
        assert restored_post.post.published_at is not None
        assert restored_post.post.published_at.tzinfo is timezone.utc
    assert author.synced_at is offset
    assert locked.synced_at is offset
    assert locked.post.created_at is offset
    assert locked.post.updated_at is offset
    assert locked.post.published_at is offset


@pytest.mark.parametrize('decoder', [decode_author_record, _decode_locked])
@pytest.mark.parametrize('version', [True, '1', 1.0, None])
def test_schema_version_requires_an_exact_integer(
    decoder: Decoder,
    version: object,
) -> None:
    with pytest.raises(InvalidAuthorRecordError) as error:
        decoder(_json_bytes({'schema_version': version}))
    assert not isinstance(error.value, UnsupportedAuthorSchemaError)


@pytest.mark.parametrize('decoder', [decode_author_record, _decode_locked])
@pytest.mark.parametrize('version', [0, 2])
def test_unsupported_schema_precedes_body_validation(
    decoder: Decoder,
    version: int,
) -> None:
    with pytest.raises(UnsupportedAuthorSchemaError):
        decoder(_json_bytes({'schema_version': version, 'future_body': {}}))


@pytest.mark.parametrize('decoder', [decode_author_record, _decode_locked])
@pytest.mark.parametrize('data', [b'{', b'\xff', b'null', b'[]', b'1', b'{}'])
def test_malformed_documents_raise_record_errors(decoder: Decoder, data: bytes) -> None:
    with pytest.raises(InvalidAuthorRecordError):
        decoder(data)


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('author', ''),
        ('author', True),
        ('title', 12),
        ('remote_post_count', -1),
        ('remote_post_count', True),
        ('remote_post_count', '42'),
        ('remote_post_count', float('inf')),
        ('avatar_path', '../outside.jpg'),
        ('cover_path', 'C:/cover.jpg'),
    ],
)
def test_invalid_author_fields_fail_on_read_and_write(
    author: AuthorInfo,
    field: str,
    value: object,
) -> None:
    document = deepcopy(AUTHOR_DOCUMENT)
    document['author'][field] = value
    setattr(author, field, value)

    with pytest.raises(InvalidAuthorRecordError):
        decode_author_record(_json_bytes(document))
    with pytest.raises(InvalidAuthorRecordError):
        encode_author_record(author)


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('id', ''),
        ('author', 'other'),
        ('likes', True),
        ('tier_price_rub', -1),
        ('post_price_rub', float('nan')),
        ('tags', [False]),
    ],
)
def test_invalid_locked_metadata_fails_on_read_and_write(
    locked: LockedPost,
    field: str,
    value: object,
) -> None:
    document = deepcopy(LOCKED_DOCUMENT)
    document['posts'][POST_ID]['post'][field] = value
    setattr(locked.post, field, value)

    with pytest.raises(InvalidAuthorRecordError):
        _decode_locked(_json_bytes(document))
    with pytest.raises(InvalidAuthorRecordError):
        encode_locked_posts('author', {POST_ID: locked})


def test_locked_teaser_path_is_author_relative(locked: LockedPost) -> None:
    document = deepcopy(LOCKED_DOCUMENT)
    locked.teaser_path = document['posts'][POST_ID]['teaser_path'] = '..\\teaser.jpg'

    with pytest.raises(InvalidAuthorRecordError):
        _decode_locked(_json_bytes(document))
    with pytest.raises(InvalidAuthorRecordError):
        encode_locked_posts('author', {POST_ID: locked})


def test_locked_map_keys_match_full_post_ids(locked: LockedPost) -> None:
    document = deepcopy(LOCKED_DOCUMENT)
    document['posts'] = {POST_ID[:8]: document['posts'][POST_ID]}

    with pytest.raises(InvalidAuthorRecordError):
        _decode_locked(_json_bytes(document))
    with pytest.raises(InvalidAuthorRecordError):
        encode_locked_posts('author', {POST_ID[:8]: locked})


def test_empty_locked_records_still_validate_author() -> None:
    document: JsonObject = {'schema_version': 1, 'author': 'other', 'posts': {}}

    with pytest.raises(InvalidAuthorRecordError):
        _decode_locked(_json_bytes(document))
    with pytest.raises(InvalidAuthorRecordError):
        encode_locked_posts('', {})
    with pytest.raises(InvalidAuthorRecordError):
        decode_locked_posts(encode_locked_posts('author', {}), author='')


def test_naive_sync_dates_are_rejected_on_read_and_write(
    author: AuthorInfo,
    locked: LockedPost,
) -> None:
    naive = NOW.replace(tzinfo=None)
    author.synced_at = locked.synced_at = naive
    author_wire = deepcopy(AUTHOR_DOCUMENT)
    author_wire['author']['synced_at'] = naive.isoformat()
    locked_wire = deepcopy(LOCKED_DOCUMENT)
    locked_wire['posts'][POST_ID]['synced_at'] = naive.isoformat()

    with pytest.raises(InvalidAuthorRecordError):
        decode_author_record(_json_bytes(author_wire))
    with pytest.raises(InvalidAuthorRecordError):
        _decode_locked(_json_bytes(locked_wire))
    with pytest.raises(InvalidAuthorRecordError):
        encode_author_record(author)
    with pytest.raises(InvalidAuthorRecordError):
        encode_locked_posts('author', {POST_ID: locked})


def test_unknown_fields_are_not_silently_lost() -> None:
    author_wire = deepcopy(AUTHOR_DOCUMENT)
    locked_wire = deepcopy(LOCKED_DOCUMENT)
    for target, document, decoder in (
        (author_wire, author_wire, decode_author_record),
        (author_wire['author'], author_wire, decode_author_record),
        (locked_wire, locked_wire, _decode_locked),
        (locked_wire['posts'][POST_ID], locked_wire, _decode_locked),
        (locked_wire['posts'][POST_ID]['post'], locked_wire, _decode_locked),
    ):
        target['future_field'] = 'must survive'
        with pytest.raises(InvalidAuthorRecordError):
            decoder(_json_bytes(document))
        del target['future_field']


def test_errors_do_not_expose_saved_values(
    author: AuthorInfo,
    locked: LockedPost,
) -> None:
    private_value = 'private-record-value-6b1e97'
    for target, field in ((author, 'remote_post_count'), (locked.post, 'likes')):
        setattr(target, field, private_value)
    author_wire = deepcopy(AUTHOR_DOCUMENT)
    author_wire['author']['remote_post_count'] = private_value
    locked_wire = deepcopy(LOCKED_DOCUMENT)
    locked_wire['posts'][POST_ID]['post']['likes'] = private_value
    operations = (
        lambda: encode_author_record(author),
        lambda: encode_locked_posts('author', {POST_ID: locked}),
        lambda: decode_author_record(_json_bytes(author_wire)),
        lambda: _decode_locked(_json_bytes(locked_wire)),
    )

    for operation in operations:
        with pytest.raises(InvalidAuthorRecordError) as error:
            operation()
        assert private_value not in str(error.value)
        assert private_value not in ''.join(format_exception(error.value))


def test_invalid_locked_keys_do_not_leak_into_error_locations() -> None:
    private_key = 'private-locked-post-key-9d4ac1'
    document = deepcopy(LOCKED_DOCUMENT)
    observation = document['posts'].pop(POST_ID)
    observation['post']['likes'] = 'invalid'
    document['posts'][private_key] = observation

    with pytest.raises(InvalidAuthorRecordError) as error:
        _decode_locked(_json_bytes(document))

    assert private_key not in str(error.value)
    assert private_key not in ''.join(format_exception(error.value))


@pytest.mark.parametrize('timestamp', [1700000000, '1700000000'])
def test_author_sync_requires_iso_datetime_text(timestamp: int | str) -> None:
    document = deepcopy(AUTHOR_DOCUMENT)
    document['author']['synced_at'] = timestamp

    with pytest.raises(InvalidAuthorRecordError):
        decode_author_record(_json_bytes(document))


@pytest.mark.parametrize('timestamp', [1700000000, '1700000000'])
def test_locked_sync_requires_iso_datetime_text(timestamp: int | str) -> None:
    document = deepcopy(LOCKED_DOCUMENT)
    document['posts'][POST_ID]['synced_at'] = timestamp

    with pytest.raises(InvalidAuthorRecordError):
        _decode_locked(_json_bytes(document))


@pytest.mark.parametrize('timestamp', [1700000000, '1700000000'])
def test_locked_post_dates_require_iso_datetime_text(timestamp: int | str) -> None:
    document = deepcopy(LOCKED_DOCUMENT)
    document['posts'][POST_ID]['post']['created_at'] = timestamp

    with pytest.raises(InvalidAuthorRecordError):
        _decode_locked(_json_bytes(document))


def test_read_only_mapping_can_be_encoded(locked: LockedPost) -> None:
    observations = MappingProxyType({POST_ID: locked})

    encoded = encode_locked_posts('author', observations)

    assert encoded == _json_bytes(LOCKED_DOCUMENT)
    assert _decode_locked(encoded) == observations
