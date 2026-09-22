"""Counting shapes: what the observer keeps from an answer and what it drops."""

from __future__ import annotations

import pytest
from api_schema.shapes import MAX_VOCABULARY_SIZE, ObjectShape, json_type, observe


def test_required_is_presence_in_every_sample():
    """A key seen in half of the posts must not become required."""
    shape = ObjectShape()
    observe(shape, {'id': 'a', 'price': 0})
    observe(shape, {'id': 'b'})

    assert shape.samples == 2
    assert shape.fields['id'].present == 2
    assert shape.fields['price'].present == 1


def test_types_and_null_are_counted_apart():
    """A null once in a hundred answers is what breaks a strict model."""
    shape = ObjectShape()
    observe(shape, {'title': 'x'})
    observe(shape, {'title': None})
    observe(shape, {'title': 3.5})

    assert shape.fields['title'].types == {'string': 1, 'null': 1, 'number': 1}


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
    shape = ObjectShape()
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

    variants = shape.fields['data'].variants
    assert variants is not None
    assert sorted(variants) == ['file', 'text']
    assert variants['text'].samples == 2
    assert sorted(variants['text'].fields) == ['content', 'modificator', 'type']
    assert sorted(variants['file'].fields) == ['size', 'title', 'type']


def test_split_array_rejects_items_without_a_type():
    """A chunk without `type` is a shape the tool cannot file; it must say so."""
    shape = ObjectShape()
    with pytest.raises(ValueError, match=r'data\[\]: expected objects'):
        observe(shape, {'data': [{'content': 'no type here'}]})


def test_nested_objects_and_plain_arrays_recurse():
    shape = ObjectShape()
    observe(shape, {'extra': {'isLast': True}, 'tags': ['a', 'b']})

    extra = shape.fields['extra'].object
    assert extra is not None
    assert extra.fields['isLast'].types == {'boolean': 1}
    tags = shape.fields['tags'].items
    assert tags is not None
    assert tags.present == 2


def test_only_vocabulary_keys_keep_token_values():
    """A post title must never land in the schema, even when it is one word."""
    shape = ObjectShape()
    observe(shape, {'uploadStatus': 'ok', 'title': 'ok', 'url': 'https://x.example/a'})

    assert shape.fields['uploadStatus'].vocabulary == {'ok'}
    assert shape.fields['title'].vocabulary == set()
    assert shape.fields['url'].vocabulary == set()


def test_free_text_in_a_vocabulary_key_drops_the_list():
    shape = ObjectShape()
    observe(shape, {'type': 'ok_video'})
    observe(shape, {'type': 'Hello world'})

    assert shape.fields['type'].vocabulary is None


def test_too_many_values_is_free_text():
    shape = ObjectShape()
    for index in range(MAX_VOCABULARY_SIZE + 1):
        observe(shape, {'type': f'kind_{index}'})

    assert shape.fields['type'].vocabulary is None


def test_uuid_and_uri_flags_survive_only_unanimous_strings():
    shape = ObjectShape()
    observe(shape, {'id': '10000000-0000-4000-8000-000000000001', 'url': 'https://a'})
    observe(shape, {'id': '10000000-0000-4000-8000-000000000002', 'url': ''})

    assert shape.fields['id'].uuid_like
    assert not shape.fields['id'].uri_like
    assert not shape.fields['url'].uri_like
