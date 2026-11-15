from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter, ValidationError

from boosty_downloader.viewer.api_models import (
    Author,
    BulkMarksRequest,
    BulkMarksResult,
    ErrorBody,
    ErrorResponse,
    FavoriteMarkRequest,
    MarkRequest,
    MarkResult,
    MediaCounts,
    MediaFilters,
    MediaItem,
    MediaPage,
    MediaPost,
    MediaStorage,
    MediaViewCounts,
    MonthCount,
    OpenerCapabilities,
    OpenMediaRequest,
    OpenPostRequest,
    PositionRequest,
    PostDetail,
    PostFilters,
    PostList,
    PostRow,
    SearchMatch,
    SearchRun,
    SeenMarkRequest,
    TagCount,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

_CREATED_AT = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
_MARK_REQUEST = TypeAdapter(MarkRequest)


def _row(**changes: object) -> PostRow:
    data: dict[str, object] = {
        'id': 'post-id',
        'title': 'Saved <title>',
        'created_at': _CREATED_AT,
        'access': 'open',
    }
    return PostRow.model_validate(data | changes)


def _media(**changes: object) -> MediaItem:
    data: dict[str, object] = {
        'id': 'opaque.post-and-piece',
        'post_id': 'post-id',
        'created_at': _CREATED_AT,
        'kind': 'audio',
        'path': 'post-folder/track.mp3',
        'size': 24,
        'file_type': 'audio',
    }
    return MediaItem.model_validate(data | changes)


def test_nested_post_list_keeps_plain_text_runs_and_explicit_nulls():
    match = SearchMatch(title=[SearchRun(text='<title>', matched=True)])
    result = PostList(
        rows=[_row(match=match)],
        months=[MonthCount(month='2026-11', count=1)],
        total=1,
    )
    body = json.loads(result.model_dump_json())
    assert body['rows'][0] == {
        'id': 'post-id',
        'title': 'Saved <title>',
        'created_at': '2026-11-09T12:00:00Z',
        'access': 'open',
        'tier': None,
        'cover_path': None,
        'counts': {'images': 0, 'videos': 0, 'files': 0, 'audio': 0},
        'missing_media': 0,
        'seen': False,
        'favorite': False,
        'updated': False,
        'match': {'title': [{'text': '<title>', 'matched': True}], 'text': None},
    }
    assert body['months'] == [{'month': '2026-11', 'count': 1}]
    assert body['total'] == 1
    assert PostList.model_validate_json(result.model_dump_json()) == result


def test_mark_result_retains_flat_author_totals_and_storage():
    result = MarkResult(
        post=_row(seen=True),
        author=Author(
            name='creator',
            title='The author',
            description='About the author',
            posts=3,
            locked=1,
            unseen=1,
            favorites=2,
            storage=MediaStorage(audio=24, videos=100),
        ),
    )
    body = result.model_dump(mode='json')
    assert body['post']['seen'] is True
    assert body['author'] == {
        'name': 'creator',
        'title': 'The author',
        'description': 'About the author',
        'avatar_url': None,
        'cover_url': None,
        'posts': 3,
        'locked': 1,
        'unseen': 1,
        'favorites': 2,
        'storage': {'images': 0, 'videos': 100, 'files': 0, 'audio': 24},
    }


def test_locked_post_detail_keeps_saved_body_and_both_prices():
    detail = PostDetail.model_validate(
        _row(access='locked').model_dump()
        | {
            'tags': ['Exact tag', 'Exact tag'],
            'tier_price_rub': 150,
            'post_price_rub': 50,
            'boosty_url': 'https://boosty.to/creator/posts/post-id',
            'body_html': '<p>Retained body</p>',
            'media': [_media()],
            'has_folder': True,
        }
    )
    body = detail.model_dump(mode='json')
    assert body['access'] == 'locked'
    assert body['body_html'] == '<p>Retained body</p>'
    assert body['tier_price_rub'] == 150
    assert body['post_price_rub'] == 50
    assert body['tags'] == ['Exact tag', 'Exact tag']
    assert body['has_folder'] is True
    assert body['media'][0]['post_id'] == body['id']


def test_media_page_uses_opaque_ids_relative_paths_and_shared_post_data():
    item = _media(removed=True)
    page = MediaPage(
        items=[item],
        posts={'post-id': MediaPost(title='Saved title', favorite=True)},
        counts=MediaViewCounts(all=1, audio=1),
        missing=2,
    )
    body = page.model_dump(mode='json')
    assert body['items'][0] == {
        'id': 'opaque.post-and-piece',
        'post_id': 'post-id',
        'created_at': '2026-11-09T12:00:00Z',
        'kind': 'audio',
        'path': 'post-folder/track.mp3',
        'thumb_path': None,
        'title': None,
        'filename': None,
        'artist': None,
        'size': 24,
        'width': None,
        'height': None,
        'duration_s': None,
        'position_s': None,
        'finished': False,
        'file_type': 'audio',
        'removed': True,
    }
    assert body['posts'] == {
        'post-id': {
            'title': 'Saved title',
            'cover_path': None,
            'seen': False,
            'favorite': True,
        }
    }
    assert body['counts'] == {
        'all': 1,
        'images': 0,
        'videos': 0,
        'audio': 1,
        'files': 0,
    }
    assert body['missing'] == 2


def test_response_defaults_include_all_null_and_empty_values():
    assert PostList().model_dump() == {'rows': [], 'months': [], 'total': 0}
    assert _row().model_dump()['match'] is None
    assert OpenerCapabilities(
        open=False, reveal=False, folders=False, sep='/'
    ).model_dump() == {
        'open': False,
        'reveal': False,
        'folders': False,
        'system': None,
        'root': None,
        'sep': '/',
    }


def test_response_models_reject_assignment():
    row = _row()
    with pytest.raises(ValidationError, match='frozen_instance'):
        row.title = 'Changed'


def test_default_containers_belong_to_each_model():
    first = MediaPage()
    second = MediaPage()
    first.items.append(_media())
    first.posts['post-id'] = MediaPost(title='Saved title')
    assert second.items == []
    assert second.posts == {}


@pytest.mark.parametrize(
    ('model', 'data'),
    [
        (MediaCounts, {'images': -1}),
        (MediaStorage, {'audio': -1}),
        (MediaViewCounts, {'all': -1}),
        (BulkMarksResult, {'count': -1}),
        (TagCount, {'tag': 'tag', 'count': -1}),
        (MonthCount, {'month': '2026-13', 'count': 1}),
        (MonthCount, {'month': '2026-1', 'count': 1}),
        (MediaFilters, {'view': 'video'}),
        (PostFilters, {'kind': 'boosty_video'}),
        (PostFilters, {'order': 'random'}),
        (SearchRun, {'text': 'hit', 'matched': True, 'html': '<b>hit</b>'}),
        (ErrorBody, {'code': 'failure', 'message': 'Failed.', 'details': []}),
    ],
)
def test_invalid_response_or_filter_values_are_rejected(
    model: type[BaseModel], data: dict[str, object]
):
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize(
    'changes',
    [
        {'created_at': datetime(2026, 11, 9, 12)},  # noqa: DTZ001
        {'access': 'private'},
        {'author': 'creator'},
    ],
)
def test_post_row_rejects_naive_time_unknown_access_and_repeated_author(
    changes: dict[str, object],
):
    with pytest.raises(ValidationError):
        _row(**changes)


@pytest.mark.parametrize(
    'changes',
    [
        {'created_at': '2026-11-09T12:00:00'},
        {'kind': 'external_video'},
        {'size': None},
        {'size': -1},
        {'width': -1},
        {'file_type': 'unknown'},
        {'post_title': 'repeated'},
    ],
)
def test_media_rejects_invalid_metadata(changes: dict[str, object]):
    with pytest.raises(ValidationError):
        _media(**changes)


def test_normalized_filters_serialize_every_default():
    assert PostFilters().model_dump() == {
        'q': '',
        'kind': None,
        'unseen': False,
        'fav': False,
        'tag': None,
        'locked': False,
        'incomplete': False,
        'order': 'newest',
    }
    assert MediaFilters().model_dump() == {
        'view': 'all',
        'order': 'newest',
        'unseen': False,
        'fav': False,
    }


@pytest.mark.parametrize(
    ('body', 'expected'),
    [
        ({'seen': True}, SeenMarkRequest(seen=True)),
        ({'seen': False}, SeenMarkRequest(seen=False)),
        ({'favorite': True}, FavoriteMarkRequest(favorite=True)),
        ({'favorite': False}, FavoriteMarkRequest(favorite=False)),
    ],
)
def test_marks_accept_exactly_one_boolean_field(
    body: dict[str, object], expected: MarkRequest
):
    assert _MARK_REQUEST.validate_json(json.dumps(body)) == expected


@pytest.mark.parametrize(
    'body',
    [
        {},
        {'seen': True, 'favorite': False},
        {'seen': None},
        {'seen': 'true'},
        {'seen': 1},
        {'favorite': 'false'},
        {'favorite': 0},
        {'favorite': None},
        {'seen': True, 'extra': 1},
        None,
    ],
)
def test_marks_reject_missing_ambiguous_and_coerced_flags(body: object):
    with pytest.raises(ValidationError):
        _MARK_REQUEST.validate_json(json.dumps(body))


def test_bulk_marks_keep_complete_filters_in_the_body():
    request = BulkMarksRequest.model_validate(
        {'seen': False, 'filters': {'kind': 'videos', 'tag': 'Tag'}}
    )
    assert request.filters.kind == 'videos'
    assert request.filters.tag == 'Tag'
    assert request.model_dump()['filters']['order'] == 'newest'
    assert request.seen is False


@pytest.mark.parametrize(
    ('model', 'body'),
    [
        (BulkMarksRequest, {'seen': 1, 'filters': {}}),
        (BulkMarksRequest, {'seen': True}),
        (BulkMarksRequest, {'seen': True, 'filters': {'fav': 'true'}}),
        (OpenMediaRequest, {'reveal': 'false'}),
        (OpenMediaRequest, {'reveal': None}),
        (OpenMediaRequest, {'reveal': 0}),
        (OpenMediaRequest, {}),
        (OpenPostRequest, {'path': 'private'}),
    ],
)
def test_write_requests_reject_coercion_missing_and_unknown_fields(
    model: type[BaseModel], body: dict[str, object]
):
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(body))


def test_opener_requests_accept_the_documented_body_shapes():
    assert OpenMediaRequest(reveal=False).model_dump() == {'reveal': False}
    assert OpenPostRequest.model_validate_json('{}').model_dump() == {}


@pytest.mark.parametrize('value', [0, 12, 12.5])
def test_position_accepts_integer_and_fractional_json_numbers(value: float):
    request = PositionRequest.model_validate_json(
        json.dumps({'seconds': value, 'duration': value})
    )
    assert request.seconds == value
    assert request.duration == value


@pytest.mark.parametrize('field', ['seconds', 'duration'])
@pytest.mark.parametrize(
    'value', [True, False, '12', None, -1, float('nan'), float('inf'), -float('inf')]
)
def test_position_rejects_nonfinite_negative_and_coerced_numbers(
    field: str, value: object
):
    body: dict[str, object] = {'seconds': 12, 'duration': 100}
    body[field] = value
    with pytest.raises(ValidationError):
        PositionRequest.model_validate_json(json.dumps(body))


@pytest.mark.parametrize('body', [{'seconds': 1}, {'duration': 10}, {}])
def test_position_requires_both_seconds_and_duration(body: dict[str, object]):
    with pytest.raises(ValidationError):
        PositionRequest.model_validate(body)


def test_error_envelope_keeps_the_machine_code_and_display_message():
    response = ErrorResponse(error=ErrorBody(code='not_found', message='Not found.'))
    assert response.model_dump() == {
        'error': {'code': 'not_found', 'message': 'Not found.'}
    }
