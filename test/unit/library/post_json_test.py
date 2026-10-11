"""The versioned record format preserves complete snapshots across restarts."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from json import dumps, loads
from traceback import format_exception
from typing import Any, TypeAlias

import pytest

from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
from boosty_downloader.application.media_paths import DiskSnapshot
from boosty_downloader.application.reconcile import prepare_record, reconcile
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library._post_json import (
    decode_post_record,
    encode_post_record,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidPostRecordError,
    UnsupportedPostSchemaError,
)

JsonObject: TypeAlias = dict[str, Any]
TextFragment = PostDataChunkText.TextFragment
NOW = datetime(2026, 10, 9, 12, 30, 45, 123456, tzinfo=timezone.utc)
AUDIO_ID = 'audio:lesson'
GOLDEN_RECORD = """{
  "schema_version": 1,
  "post": {
    "id": "post-1",
    "author": "author",
    "url": "https://boosty.to/author/posts/post-1",
    "title": "Урок 🚀",
    "created_at": "2026-10-09T12:30:45.123456Z",
    "updated_at": "2026-10-09T12:30:45.123456Z",
    "published_at": "2026-10-09T12:30:45.123456Z",
    "tags": ["обучение", "audio"],
    "tier": "Подписка",
    "tier_price_rub": 99.5,
    "post_price_rub": 0.0,
    "likes": 3,
    "comments": 2,
    "content_counters": {"audio_file": 1, "future_api_kind": 0}
  },
  "sync": {
    "first_downloaded_at": "2026-10-09T12:30:45.123456Z",
    "synced_at": "2026-10-09T12:30:45.123456Z",
    "page_template": 2,
    "origin": "api"
  },
  "blocks": [
    {
      "type": "text",
      "fragments": [
        {
          "type": "text",
          "text": "Привет",
          "link_url": null,
          "header_level": 0,
          "style": {"bold": false, "italic": false, "underline": false}
        }
      ]
    },
    {"type": "media", "media_id": "audio:lesson"}
  ],
  "media": {
    "audio:lesson": {
      "kind": "audio",
      "status": "downloaded",
      "added_at": "2026-10-09T12:30:45.123456Z",
      "position": 0,
      "removed_at": "2026-10-09T12:30:45.123456Z",
      "path": "audio/Урок.mp3",
      "size": 0,
      "title": "Урок",
      "filename": "Урок.mp3",
      "artist": "Автор",
      "duration": "PT1.234567S",
      "width": 640,
      "height": 480,
      "preview_path": "previews/Обложка.jpg",
      "error": null
    }
  }
}"""


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id='post-1',
            author='author',
            url='https://boosty.to/author/posts/post-1',
            title='Урок 🚀',
            created_at=NOW,
            updated_at=NOW,
            published_at=NOW,
            tags=['обучение', 'audio'],
            tier='Подписка',
            tier_price_rub=99.5,
            post_price_rub=0.0,
            likes=3,
            comments=2,
            content_counters={'audio_file': 1, 'future_api_kind': 0},
        ),
        sync=PostSync(NOW, NOW, page_template=2),
        blocks=[TextBlock([TextFragment('Привет')]), MediaBlock(AUDIO_ID)],
        media={
            AUDIO_ID: MediaEntry(
                kind=MediaKind.audio,
                status=MediaStatus.downloaded,
                added_at=NOW,
                position=0,
                removed_at=NOW,
                path='audio/Урок.mp3',
                size=0,
                title='Урок',
                filename='Урок.mp3',
                artist='Автор',
                duration=timedelta(seconds=1, microseconds=234567),
                width=640,
                height=480,
                preview_path='previews/Обложка.jpg',
            )
        },
    )


def _json_section(document: JsonObject, section: str) -> JsonObject:
    if section == 'media':
        return document['media'][AUDIO_ID]
    return document[section]


def _record_section(
    record: StoredPost,
    section: str,
) -> PostMetadata | PostSync | MediaEntry:
    match section:
        case 'post':
            return record.post
        case 'sync':
            return record.sync
        case 'media':
            return record.media[AUDIO_ID]
    raise AssertionError(section)


def test_encoding_matches_independent_full_json_and_readable_format(
    record: StoredPost,
) -> None:
    expected = dumps(loads(GOLDEN_RECORD), ensure_ascii=False, indent=2) + '\n'

    assert encode_post_record(record) == expected.encode('utf-8')


def test_decoding_independent_full_json_restores_domain_types(
    record: StoredPost,
) -> None:
    assert decode_post_record(GOLDEN_RECORD.encode('utf-8')) == record


def test_empty_collections_and_optional_defaults_survive() -> None:
    record = StoredPost(
        PostMetadata('p', 'a', 'https://example.com', '', NOW, NOW),
        PostSync(NOW, NOW),
    )

    encoded = encode_post_record(record)
    document = loads(encoded)

    assert decode_post_record(encoded) == record
    assert document['blocks'] == []
    assert document['media'] == {}
    assert document['post']['tags'] == []
    assert document['post']['content_counters'] == {}
    assert document['post']['published_at'] is None
    assert document['sync'] == {
        'first_downloaded_at': NOW.isoformat().replace('+00:00', 'Z'),
        'synced_at': NOW.isoformat().replace('+00:00', 'Z'),
        'page_template': None,
        'origin': 'api',
    }


def test_all_media_kinds_states_and_inventory_order_survive(record: StoredPost) -> None:
    states = {
        MediaKind.external_video: MediaStatus.unavailable,
        MediaKind.image: MediaStatus.pending,
        MediaKind.file: MediaStatus.downloaded,
        MediaKind.audio: MediaStatus.failed,
        MediaKind.boosty_video: MediaStatus.deleted,
    }
    record.media = {
        f'{kind.value}:piece': replace(
            record.media[AUDIO_ID],
            kind=kind,
            status=status,
            position=position,
            error='Ошибка загрузки',
        )
        for position, (kind, status) in enumerate(states.items())
    }
    record.blocks = [MediaBlock(media_id) for media_id in reversed(record.media)]

    restored = decode_post_record(encode_post_record(record))

    assert restored == record
    assert list(restored.media) == list(record.media)


def test_serialization_and_repeated_reads_produce_independent_snapshots(
    record: StoredPost,
) -> None:
    original = deepcopy(record)
    encoded = encode_post_record(record)
    first = decode_post_record(encoded)
    second = decode_post_record(encoded)
    first.post.tags.clear()
    first.post.content_counters.clear()
    first.sync.page_template = 99
    first.media[AUDIO_ID].title = 'Changed'
    text = first.blocks[0]
    assert isinstance(text, TextBlock)
    fragment = text.fragments[0]
    assert isinstance(fragment, TextFragment)
    fragment.style.bold = True
    first.blocks.clear()

    assert second == original
    assert record == original
    assert decode_post_record(encoded) == original


@pytest.mark.parametrize(
    ('section', 'field'),
    [
        ('post', 'created_at'),
        ('post', 'updated_at'),
        ('post', 'published_at'),
        ('sync', 'first_downloaded_at'),
        ('sync', 'synced_at'),
        ('media', 'added_at'),
        ('media', 'removed_at'),
    ],
)
def test_every_datetime_normalizes_offsets_without_mutation(
    record: StoredPost,
    section: str,
    field: str,
) -> None:
    offset_time = NOW.astimezone(timezone(timedelta(hours=3)))
    target = _record_section(record, section)
    setattr(target, field, offset_time)
    wire = loads(GOLDEN_RECORD)
    _json_section(wire, section)[field] = offset_time.isoformat()

    for restored in (
        decode_post_record(encode_post_record(record)),
        decode_post_record(dumps(wire).encode()),
    ):
        assert getattr(_record_section(restored, section), field).tzinfo is timezone.utc
    assert getattr(target, field).tzinfo is offset_time.tzinfo


@pytest.mark.parametrize(
    'section', ['post', 'sync', 'blocks', 'media', 'schema_version']
)
def test_missing_envelope_fields_are_invalid(section: str) -> None:
    document = loads(GOLDEN_RECORD)
    del document[section]

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())


@pytest.mark.parametrize('version', [True, False, '1', 1.0, None, [], {}])
def test_schema_version_requires_an_exact_integer(version: object) -> None:
    document = loads(GOLDEN_RECORD)
    document['schema_version'] = version

    with pytest.raises(InvalidPostRecordError) as error:
        decode_post_record(dumps(document).encode())
    assert not isinstance(error.value, UnsupportedPostSchemaError)


@pytest.mark.parametrize('version', [0, -1, 2])
def test_unsupported_version_is_detected_before_reading_its_body(version: int) -> None:
    with pytest.raises(UnsupportedPostSchemaError):
        decode_post_record(
            dumps({'schema_version': version, 'future_body': {}}).encode()
        )


@pytest.mark.parametrize(
    'document',
    [
        b'{',
        b'\xff',
        b'null',
        b'[]',
        b'1',
        pytest.param(b'[' * 2000 + b'0' + b']' * 2000, id='excessive-nesting'),
    ],
)
def test_malformed_json_utf8_and_non_object_roots_are_invalid(document: bytes) -> None:
    with pytest.raises(InvalidPostRecordError):
        decode_post_record(document)


@pytest.mark.parametrize('section', ['root', 'post', 'sync', 'media'])
def test_unknown_fields_are_not_silently_lost(section: str) -> None:
    document = loads(GOLDEN_RECORD)
    target = document if section == 'root' else _json_section(document, section)
    target['future_field'] = 'must not disappear'

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())


@pytest.mark.parametrize(
    ('section', 'field', 'value'),
    [
        pytest.param('post', 'id', '', id='empty-post-id'),
        pytest.param('post', 'author', '', id='empty-author'),
        pytest.param('post', 'likes', '3', id='coerced-counter'),
        pytest.param('post', 'comments', True, id='boolean-counter'),
        pytest.param('post', 'likes', -1, id='negative-likes'),
        pytest.param('post', 'comments', -1, id='negative-comments'),
        pytest.param(
            'post', 'content_counters', {'future': -1}, id='negative-api-count'
        ),
        pytest.param('post', 'tier_price_rub', -0.01, id='negative-tier-price'),
        pytest.param('post', 'post_price_rub', -1, id='negative-post-price'),
        pytest.param('post', 'tier_price_rub', float('nan'), id='nan-price'),
        pytest.param('post', 'post_price_rub', float('inf'), id='infinite-price'),
        pytest.param('post', 'tags', [1], id='non-string-tag'),
        pytest.param('sync', 'origin', 'import', id='unknown-origin'),
        pytest.param('sync', 'page_template', True, id='boolean-template'),
        pytest.param('media', 'kind', 'movie', id='unknown-kind'),
        pytest.param('media', 'status', 'ready', id='unknown-status'),
        pytest.param('media', 'size', -1, id='negative-size'),
        pytest.param('media', 'size', True, id='boolean-size'),
        pytest.param('media', 'position', -1, id='negative-position'),
        pytest.param('media', 'width', -1, id='negative-width'),
        pytest.param('media', 'height', -1, id='negative-height'),
    ],
)
def test_invalid_fields_fail_on_read_and_mutated_domain_write(
    record: StoredPost,
    section: str,
    field: str,
    value: object,
) -> None:
    document = loads(GOLDEN_RECORD)
    _json_section(document, section)[field] = value
    setattr(_record_section(record, section), field, value)

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


@pytest.mark.parametrize(
    ('section', 'field'),
    [
        ('post', 'created_at'),
        ('post', 'updated_at'),
        ('post', 'published_at'),
        ('sync', 'first_downloaded_at'),
        ('sync', 'synced_at'),
        ('media', 'added_at'),
        ('media', 'removed_at'),
    ],
)
def test_naive_dates_are_rejected_on_read_and_write(
    record: StoredPost,
    section: str,
    field: str,
) -> None:
    naive = NOW.replace(tzinfo=None)
    document = loads(GOLDEN_RECORD)
    _json_section(document, section)[field] = naive.isoformat()
    setattr(_record_section(record, section), field, naive)

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


@pytest.mark.parametrize('duration', [-1, '-PT1S', 1.25, '00:00:01.23'])
def test_duration_requires_a_nonnegative_iso8601_string(duration: object) -> None:
    document = loads(GOLDEN_RECORD)
    document['media'][AUDIO_ID]['duration'] = duration

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())


def test_negative_domain_duration_is_rejected(record: StoredPost) -> None:
    record.media[AUDIO_ID].duration = timedelta(microseconds=-1)

    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


@pytest.mark.parametrize('field', ['path', 'preview_path'])
@pytest.mark.parametrize(
    'path',
    [
        '',
        '.',
        'audio/',
        '/audio/a.mp3',
        'C:audio.mp3',
        'C:/audio.mp3',
        'audio\\a.mp3',
        'audio/../a.mp3',
        '../a.mp3',
        'audio/\x00a.mp3',
    ],
)
def test_unsafe_or_non_file_paths_are_rejected_on_read_and_write(
    record: StoredPost,
    field: str,
    path: str,
) -> None:
    document = loads(GOLDEN_RECORD)
    document['media'][AUDIO_ID][field] = path
    setattr(record.media[AUDIO_ID], field, path)

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


@pytest.mark.parametrize('media_id', ['', 'audio:', 'lesson', 'file:lesson'])
def test_media_identity_must_have_a_nonempty_kind_matching_key(
    record: StoredPost,
    media_id: str,
) -> None:
    document = loads(GOLDEN_RECORD)
    document['media'] = {media_id: document['media'][AUDIO_ID]}
    document['blocks'] = []
    record.media = {media_id: record.media[AUDIO_ID]}
    record.blocks = []

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


def test_dangling_body_reference_is_rejected_on_read_and_write(
    record: StoredPost,
) -> None:
    document = loads(GOLDEN_RECORD)
    document['media'] = {}
    record.media.clear()

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


@pytest.mark.parametrize('field', ['path', 'size'])
def test_downloaded_media_requires_a_path_and_recorded_size(
    record: StoredPost,
    field: str,
) -> None:
    document = loads(GOLDEN_RECORD)
    document['media'][AUDIO_ID][field] = None
    setattr(record.media[AUDIO_ID], field, None)

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


def test_real_record_producer_preserves_pending_and_zero_size_copies(
    record: StoredPost,
) -> None:
    live = LivePost(
        post=record.post,
        has_access=True,
        blocks=[MediaBlock('file:saved'), MediaBlock('boosty_video:pending')],
        media={
            'file:saved': LiveMedia(MediaKind.file, download=None),
            'boosty_video:pending': LiveMedia(MediaKind.boosty_video, download=None),
        },
    )
    prepared = prepare_record(None, live, NOW)
    assert prepared is not None
    assert prepared.media['boosty_video:pending'].path is None
    assert prepared.media['boosty_video:pending'].size is None
    assert decode_post_record(encode_post_record(prepared)) == prepared
    prepared.media['file:saved'] = replace(
        prepared.media['file:saved'],
        status=MediaStatus.downloaded,
        path='files/saved.txt',
        size=10,
    )
    observed = reconcile(
        prepared,
        live,
        DiskSnapshot({'files/saved.txt': 0}),
        [],
        NOW,
    ).record
    assert observed is not None
    assert observed.media['file:saved'].size == 0
    assert observed.media['file:saved'].status is MediaStatus.downloaded
    assert decode_post_record(encode_post_record(observed)) == observed


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        pytest.param('post', [], id='metadata-is-not-an-object'),
        pytest.param('sync', None, id='sync-is-not-an-object'),
        pytest.param('blocks', {}, id='body-is-not-an-array'),
        pytest.param('media', [], id='inventory-is-not-an-object'),
        pytest.param('blocks', [{}], id='body-tag-is-missing'),
        pytest.param('blocks', [{'type': 'unknown'}], id='body-tag-is-unknown'),
    ],
)
def test_invalid_nested_shapes_raise_the_record_error(
    field: str, value: object
) -> None:
    document = loads(GOLDEN_RECORD)
    document[field] = value

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())


def test_invalid_domain_body_raises_the_record_error(record: StoredPost) -> None:
    record.blocks = [TextBlock([TextFragment('Heading', header_level=7)])]

    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


def test_zero_duration_and_dimensions_are_valid(record: StoredPost) -> None:
    record.media[AUDIO_ID] = replace(
        record.media[AUDIO_ID],
        duration=timedelta(0),
        width=0,
        height=0,
    )

    assert decode_post_record(encode_post_record(record)) == record


@pytest.mark.parametrize(
    'date',
    ['0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00'],
)
def test_utc_overflow_is_a_record_error_on_read_and_write(
    record: StoredPost,
    date: str,
) -> None:
    document = loads(GOLDEN_RECORD)
    document['post']['created_at'] = date
    record.post.created_at = datetime.fromisoformat(date)

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)


@pytest.mark.parametrize('field', ['schema_version', 'likes'])
def test_read_tracebacks_do_not_include_invalid_saved_values(field: str) -> None:
    private_value = 'private-saved-post-6b1e97'
    document = loads(GOLDEN_RECORD)
    target = document if field == 'schema_version' else document['post']
    target[field] = private_value

    with pytest.raises(InvalidPostRecordError) as error:
        decode_post_record(dumps(document).encode())

    assert private_value not in ''.join(format_exception(error.value))


@pytest.mark.parametrize('field', ['likes', 'header_level'])
def test_write_tracebacks_do_not_include_invalid_saved_values(
    record: StoredPost,
    field: str,
) -> None:
    private_value = 'private-saved-post-6b1e97'
    fragment = TextFragment('Private fragment')
    record.blocks = [TextBlock([fragment])]
    target = record.post if field == 'likes' else fragment
    setattr(target, field, private_value)

    with pytest.raises(InvalidPostRecordError) as error:
        encode_post_record(record)

    assert private_value not in ''.join(format_exception(error.value))


@pytest.mark.parametrize(
    ('section', 'field', 'date'),
    [
        ('post', 'created_at', '0'),
        ('sync', 'synced_at', '1700000000'),
        ('media', 'added_at', '1700000000'),
    ],
)
def test_numeric_timestamp_strings_are_not_saved_datetime_values(
    section: str,
    field: str,
    date: str,
) -> None:
    document = loads(GOLDEN_RECORD)
    _json_section(document, section)[field] = date

    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(document).encode())
