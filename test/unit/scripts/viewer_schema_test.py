from __future__ import annotations

import json
from inspect import isabstract
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from pydantic import BaseModel
from viewer_schema import build_schema, main

from boosty_downloader.viewer import api_models

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest
    from pydantic.json_schema import JsonSchemaValue


def _discover_models() -> set[type[BaseModel]]:
    models: set[type[BaseModel]] = set()
    pending = list(BaseModel.__subclasses__())
    while pending:
        model = pending.pop()
        pending.extend(model.__subclasses__())
        if (
            model.__module__ == api_models.__name__
            and not model.__name__.startswith('_')
            and not isabstract(model)
        ):
            models.add(model)
    return models


def _walk_nodes(value: object) -> Iterator[JsonSchemaValue]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_nodes(child)


def _resolve(schema: JsonSchemaValue, reference: str) -> JsonSchemaValue:
    assert reference.startswith('#/')
    node = schema
    for token in reference[2:].split('/'):
        node = node[token.replace('~1', '/').replace('~0', '~')]
    return node


def _model_schema(schema: JsonSchemaValue, name: str) -> JsonSchemaValue:
    return _resolve(schema, schema['properties'][name]['$ref'])


def _validator(name: str) -> Draft202012Validator:
    schema = build_schema()
    return Draft202012Validator(
        {**_model_schema(schema, name), '$defs': schema['$defs']}
    )


def test_bundle_reaches_every_independently_discovered_api_model():
    schema = build_schema()
    models = _discover_models()
    assert set(schema['properties']) == {model.__name__ for model in models}
    assert schema['required'] == sorted(schema['properties'])
    assert list(schema['properties']) == sorted(schema['properties'])
    assert schema['additionalProperties'] is False
    for model in models:
        assert _model_schema(schema, model.__name__)['title'] == model.__name__


def test_bundle_includes_standalone_write_request_models():
    names = set(build_schema()['properties'])
    assert {
        'SeenMarkRequest',
        'FavoriteMarkRequest',
        'BulkMarksRequest',
        'PositionRequest',
        'OpenMediaRequest',
        'OpenPostRequest',
    } <= names


def test_schema_is_valid_and_all_local_references_resolve():
    schema = build_schema()
    Draft202012Validator.check_schema(schema)
    for node in _walk_nodes(schema):
        if '$ref' in node:
            assert _resolve(schema, node['$ref'])


def test_model_titles_and_descriptions_survive_without_field_titles():
    schema = build_schema()
    for name in schema['properties']:
        model = _model_schema(schema, name)
        assert model['title'] == name
        for field in model['properties'].values():
            assert 'title' not in field
    path = _model_schema(schema, 'MediaItem')['properties']['path']
    assert path['description'] == 'Author-relative file path.'


def test_serialized_fields_are_required_even_with_python_defaults():
    schema = build_schema()
    for name in schema['properties']:
        model = _model_schema(schema, name)
        assert set(model.get('required', [])) == set(model['properties'])
    post_filters = _validator('PostFilters')
    assert post_filters.is_valid(api_models.PostFilters().model_dump(mode='json'))
    assert not post_filters.is_valid({})
    media_filters = _validator('MediaFilters')
    assert media_filters.is_valid(api_models.MediaFilters().model_dump(mode='json'))
    assert not media_filters.is_valid({})


def test_nullable_search_body_is_present_and_accepts_null_or_named_runs():
    schema = _model_schema(build_schema(), 'SearchMatch')
    assert schema['properties']['text']['default'] is None
    assert {'type': 'null'} in schema['properties']['text']['anyOf']
    validator = _validator('SearchMatch')
    assert validator.is_valid({'title': [], 'text': None})
    assert validator.is_valid(
        {'title': [], 'text': [{'text': 'match', 'matched': True}]}
    )
    assert not validator.is_valid({'title': []})
    assert not validator.is_valid({'title': [], 'text': [['match', True]]})


def test_wire_literals_and_media_identity_keep_their_contracts():
    schema = build_schema()
    filters = _model_schema(schema, 'PostFilters')['properties']
    assert filters['order']['enum'] == ['newest', 'oldest']
    media = _model_schema(schema, 'MediaItem')['properties']
    assert media['kind']['enum'] == ['images', 'videos', 'files', 'audio']
    assert media['id']['type'] == 'string'
    assert 'format' not in media['id']
    assert 'pattern' not in media['id']
    assert media['file_type']['enum'] == [
        'pdf',
        'document',
        'book',
        'sheet',
        'slides',
        'image',
        'audio',
        'video',
        'archive',
        'model',
        'code',
        'font',
        'program',
        'script',
        'other',
    ]


def test_write_schemas_reject_extra_fields_and_require_numeric_position():
    opener = _validator('OpenPostRequest')
    assert opener.is_valid({})
    assert not opener.is_valid({'reveal': False})
    position = _validator('PositionRequest')
    assert position.is_valid({'seconds': 1, 'duration': 10.5})
    assert not position.is_valid({'seconds': 1})
    for value in (True, '1', -1, None):
        assert not position.is_valid({'seconds': value, 'duration': 10})
        assert not position.is_valid({'seconds': 1, 'duration': value})


def test_cli_emits_identical_utf8_json_with_a_final_newline(
    capsys: pytest.CaptureFixture[str],
):
    main()
    first = capsys.readouterr().out
    main()
    second = capsys.readouterr().out
    assert first.encode('utf-8') == second.encode('utf-8')
    assert first.endswith('\n')
    assert json.loads(first) == build_schema()
