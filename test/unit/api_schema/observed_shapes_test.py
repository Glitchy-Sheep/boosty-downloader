"""Counting shapes: what the observer keeps from an answer and what it drops."""

from __future__ import annotations

import pytest
from api_schema.observed_shapes import (
    MAX_VOCABULARY_SIZE,
    ObservedObject,
    json_type,
    observe,
)


def test_required_is_presence_in_every_sample():
    """A key seen in half of the posts must not become required."""
    shape = ObservedObject()
    observe(shape, {'id': 'a', 'price': 0})
    observe(shape, {'id': 'b'})

    assert shape.samples == 2
    assert shape.keys['id'].seen == 2
    assert shape.keys['price'].seen == 1


def test_types_and_null_are_counted_apart():
    """A null once in a hundred answers is what breaks a strict model."""
    shape = ObservedObject()
    observe(shape, {'title': 'x'})
    observe(shape, {'title': None})
    observe(shape, {'title': 3.5})

    assert shape.keys['title'].types == {'string': 1, 'null': 1, 'number': 1}


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (True, 'boolean'),
        (1, 'integer'),
        (1.5, 'number'),
        ('s', 'string'),
        ({}, 'object'),
        ([], 'array'),
        (None, 'null'),
    ],
)
def test_json_type_names(value: object, expected: str):
    """A bool is not an integer: the order of the checks matters."""
    assert json_type(value) == expected


def test_data_array_is_split_by_chunk_type():
    """One shape per chunk kind, not one blend of every key of every kind."""
    shape = ObservedObject()
    observe(
        shape,
        {
            'data': [
                {'type': 'text', 'content': 'a'},
                {'type': 'file', 'title': 'b', 'size': 1},
                {'type': 'text', 'content': 'c', 'modificator': 'BLOCK_END'},
            ]
        },
    )

    variants = shape.keys['data'].variants
    assert variants is not None
    assert sorted(variants) == ['file', 'text']
    assert variants['text'].samples == 2
    assert sorted(variants['text'].keys) == ['content', 'modificator', 'type']
    assert sorted(variants['file'].keys) == ['size', 'title', 'type']


def test_split_array_rejects_items_without_a_type():
    """A chunk without `type` is a shape the tool cannot file; it must say so."""
    shape = ObservedObject()
    with pytest.raises(ValueError, match=r'data\[\]: expected objects'):
        observe(shape, {'data': [{'content': 'no type here'}]})


def test_nested_objects_and_plain_arrays_recurse():
    shape = ObservedObject()
    observe(shape, {'extra': {'isLast': True}, 'tags': ['a', 'b']})

    extra = shape.keys['extra'].nested
    assert extra is not None
    assert extra.keys['isLast'].types == {'boolean': 1}
    tags = shape.keys['tags'].items
    assert tags is not None
    assert tags.seen == 2


def test_an_always_empty_array_has_no_item_shape():
    """Anonymous answers carry `playerUrls: []`: no items means no item schema."""
    shape = ObservedObject()
    observe(shape, {'playerUrls': []})
    observe(shape, {'playerUrls': []})

    assert shape.keys['playerUrls'].types == {'array': 2}
    assert shape.keys['playerUrls'].items is None


def test_only_vocabulary_keys_keep_token_values():
    """A post title must never land in the schema, even when it is one word."""
    shape = ObservedObject()
    observe(shape, {'uploadStatus': 'ok', 'title': 'ok', 'url': 'https://x.example/a'})

    assert shape.keys['uploadStatus'].vocabulary == {'ok'}
    assert shape.keys['title'].vocabulary == set()
    assert shape.keys['url'].vocabulary == set()


def test_free_text_in_a_vocabulary_key_drops_the_list():
    shape = ObservedObject()
    observe(shape, {'type': 'ok_video'})
    observe(shape, {'type': 'Hello world'})

    assert shape.keys['type'].vocabulary is None


def test_too_many_values_is_free_text():
    shape = ObservedObject()
    for index in range(MAX_VOCABULARY_SIZE + 1):
        observe(shape, {'type': f'kind_{index}'})

    assert shape.keys['type'].vocabulary is None


def test_uuid_and_uri_flags_survive_only_unanimous_strings():
    shape = ObservedObject()
    observe(shape, {'id': '10000000-0000-4000-8000-000000000001', 'url': 'https://a'})
    observe(shape, {'id': '10000000-0000-4000-8000-000000000002', 'url': ''})

    assert shape.keys['id'].uuid_like
    assert not shape.keys['id'].uri_like
    assert not shape.keys['url'].uri_like
