"""Rendering shapes as OpenAPI: what the document says and what it never contains."""

from __future__ import annotations

from typing import cast

import yaml
from api_schema.openapi import Observation, build_document, to_yaml
from api_schema.shapes import ObjectShape, observe

JsonDict = dict[str, object]

POST_ID = '10000000-0000-4000-8000-000000000001'
PRIVATE_TITLE = 'A title that must never reach the schema'


def _post(**overrides: object) -> JsonDict:
    post: JsonDict = {
        'id': POST_ID,
        'title': PRIVATE_TITLE,
        'hasAccess': True,
        'signedQuery': '?fake',
        'data': [
            {'type': 'text', 'content': 'hello', 'modificator': ''},
            {
                'type': 'ok_video',
                'id': POST_ID,
                'uploadStatus': 'ok',
                'playerUrls': [
                    {'type': 'medium', 'url': 'https://video.example/m.mp4'},
                    {'type': 'hls', 'url': ''},
                ],
            },
        ],
    }
    post.update(overrides)
    return post


def _observe(posts: list[JsonDict]) -> Observation:
    page = ObjectShape()
    observe(page, {'data': [], 'extra': {'offset': '', 'isLast': True}})
    post_shape = ObjectShape()
    for post in posts:
        observe(post_shape, post)
    return Observation(
        page=page,
        post=post_shape,
        captured_at='2026-09-22',
        samples={'posts': len(posts), 'pages': 1},
        unread_by_client={'Post': ['hasAccess']},
    )


def _schemas(document: JsonDict) -> dict[str, JsonDict]:
    components = cast('JsonDict', document['components'])
    return cast('dict[str, JsonDict]', components['schemas'])


def test_required_and_presence_follow_the_samples():
    """`subscriptionLevel` on locked posts only must be optional with its share."""
    document = build_document(
        _observe([_post(subscriptionLevel={'name': 'x'}), _post(), _post(), _post()])
    )

    post = _schemas(document)['Post']
    assert post['required'] == ['data', 'hasAccess', 'id', 'signedQuery', 'title']
    properties = cast('dict[str, JsonDict]', post['properties'])
    assert properties['subscriptionLevel']['x-presence'] == 0.25
    assert 'x-presence' not in properties['id']


def test_null_widens_the_type_and_formats_follow_the_strings():
    document = build_document(_observe([_post(), _post(title=None)]))

    properties = cast('dict[str, JsonDict]', _schemas(document)['Post']['properties'])
    assert properties['title']['type'] == ['string', 'null']
    assert properties['id'] == {'type': 'string', 'format': 'uuid'}


def test_chunks_become_components_told_apart_by_type():
    document = build_document(_observe([_post()]))

    schemas = _schemas(document)
    data = cast('dict[str, JsonDict]', schemas['Post']['properties'])['data']
    items = cast('JsonDict', data['items'])
    assert items['discriminator'] == {'propertyName': 'type'}
    assert items['oneOf'] == [
        {'$ref': '#/components/schemas/ChunkOkVideo'},
        {'$ref': '#/components/schemas/ChunkText'},
    ]
    video = cast('dict[str, JsonDict]', schemas['ChunkOkVideo']['properties'])
    assert video['type'] == {'type': 'string', 'const': 'ok_video'}


def test_strict_enum_for_player_urls_and_seen_values_elsewhere():
    """A new video quality name is drift; a new upload status is information."""
    document = build_document(_observe([_post()]))

    video = cast(
        'dict[str, JsonDict]', _schemas(document)['ChunkOkVideo']['properties']
    )
    player_urls = cast('dict[str, JsonDict]', video['playerUrls']['items'])
    url_type = cast('dict[str, JsonDict]', player_urls['properties'])['type']
    assert url_type['enum'] == ['hls', 'medium']
    assert video['uploadStatus']['x-seen-values'] == ['ok']
    assert 'enum' not in video['uploadStatus']


def test_empty_arrays_render_without_items():
    """`type: []` under items is invalid OpenAPI; an empty array is just an array."""
    document = build_document(_observe([_post(tags=[])]))

    properties = cast('dict[str, JsonDict]', _schemas(document)['Post']['properties'])
    assert properties['tags'] == {'type': 'array'}


def test_page_refers_to_post_and_extracts_extra():
    document = build_document(_observe([_post()]))

    schemas = _schemas(document)
    page = cast('dict[str, JsonDict]', schemas['PostsPage']['properties'])
    assert page['data'] == {
        'type': 'array',
        'items': {'$ref': '#/components/schemas/Post'},
    }
    assert page['extra'] == {'$ref': '#/components/schemas/PageExtra'}
    assert schemas['PageExtra']['required'] == ['isLast', 'offset']


def test_unread_keys_and_sample_counts_are_recorded():
    document = build_document(_observe([_post()]))

    assert _schemas(document)['Post']['x-unread-by-client'] == ['hasAccess']
    assert document['x-observed'] == {
        'captured_at': '2026-09-22',
        'samples': {'pages': 1, 'posts': 1},
    }


def test_yaml_is_deterministic_and_carries_no_values():
    """The file goes into the repo: the same answers give the same bytes and no content."""
    first = to_yaml(build_document(_observe([_post()])))
    second = to_yaml(build_document(_observe([_post()])))

    assert first == second
    assert PRIVATE_TITLE not in first
    assert POST_ID not in first
    assert 'video.example' not in first
    assert yaml.safe_load(first)['openapi'] == '3.1.0'
