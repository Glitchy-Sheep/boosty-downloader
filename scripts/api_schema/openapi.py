"""
Observed shapes rendered as an OpenAPI 3.1 document.

The document covers the two endpoints the client calls. Its schemas carry
custom fields: `x-presence` (share of samples with the key, on optional keys),
`x-seen-values` (vocabulary of a field, for reading), `x-unread-by-client`
(keys the client's models ignore) and `x-observed` at the top with sample
counts. Nothing else from the answers lands in the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from api_schema.shapes import FieldShape, ObjectShape

# A value outside these lists is drift: the client switches on them.
STRICT_ENUMS: frozenset[str] = frozenset({'data[].playerUrls[].type'})

_SCHEMAS = '#/components/schemas/'
JsonDict = dict[str, object]


@dataclass(frozen=True)
class Observation:
    """What the answers looked like, ready to be rendered."""

    # Listing answers with `data` emptied: posts are observed on their own.
    page: ObjectShape
    # Every post, from listings and single-post answers alike.
    post: ObjectShape
    captured_at: str
    samples: dict[str, int]
    # Schema name -> keys the client's models do not read.
    unread_by_client: dict[str, list[str]] = field(default_factory=dict[str, list[str]])


def build_document(observation: Observation) -> JsonDict:
    """Build the whole OpenAPI document, keys in a stable order."""
    components: dict[str, JsonDict] = {}
    post = object_schema(observation.post, '', components)
    components['Post'] = post

    page = object_schema(observation.page, '', components)
    properties = cast('JsonDict', page['properties'])
    properties['data'] = {'type': 'array', 'items': _ref('Post')}
    extra = properties.get('extra')
    if isinstance(extra, dict):
        components['PageExtra'] = cast('JsonDict', extra)
        properties['extra'] = _ref('PageExtra')
    components['PostsPage'] = page

    for name, keys in observation.unread_by_client.items():
        if name in components and keys:
            components[name]['x-unread-by-client'] = sorted(keys)

    return {
        'openapi': '3.1.0',
        'info': {
            'title': 'Boosty API as seen by boosty-downloader',
            'version': observation.captured_at,
            'description': (
                'Observed, not official: built from live answers by '
                '`task api:schema`. Only shapes and counts are recorded.'
            ),
        },
        'x-observed': {
            'captured_at': observation.captured_at,
            'samples': dict(sorted(observation.samples.items())),
        },
        'paths': _paths(),
        'components': {'schemas': dict(sorted(components.items()))},
    }


def to_yaml(document: JsonDict) -> str:
    """YAML in document order: the order is the reading order."""
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)


def object_schema(
    shape: ObjectShape, path: str, components: dict[str, JsonDict]
) -> JsonDict:
    """Render an object schema: keys sorted, required when present in every sample."""
    required: list[str] = []
    properties: JsonDict = {}
    for name, field_shape in sorted(shape.fields.items()):
        child = f'{path}.{name}' if path else name
        schema = field_schema(field_shape, child, components)
        if field_shape.present == shape.samples:
            required.append(name)
        else:
            schema['x-presence'] = round(field_shape.present / shape.samples, 2)
        properties[name] = schema
    schema: JsonDict = {'type': 'object'}
    if required:
        schema['required'] = required
    if properties:
        schema['properties'] = properties
    return schema


def field_schema(
    shape: FieldShape, path: str, components: dict[str, JsonDict]
) -> JsonDict:
    """Render the schema of one key from everything seen there."""
    types = _types(shape)
    schema: JsonDict = {'type': types[0] if len(types) == 1 else types}
    if shape.types['string']:
        if shape.uuid_like:
            schema['format'] = 'uuid'
        elif shape.uri_like:
            schema['format'] = 'uri'
        if shape.vocabulary:
            key = 'enum' if path in STRICT_ENUMS else 'x-seen-values'
            schema[key] = sorted(shape.vocabulary)
    if shape.object is not None:
        nested = object_schema(shape.object, path, components)
        schema.update({k: v for k, v in nested.items() if k != 'type'})
    if shape.variants is not None:
        schema['items'] = _variants_schema(shape.variants, path, components)
    elif shape.items is not None:
        schema['items'] = field_schema(shape.items, f'{path}[]', components)
    return schema


def _types(shape: FieldShape) -> list[str]:
    """Non-null types sorted, `null` last."""
    seen = sorted(name for name in shape.types if name != 'null')
    if shape.types['null']:
        seen.append('null')
    return seen


def _variants_schema(
    variants: dict[str, ObjectShape], path: str, components: dict[str, JsonDict]
) -> JsonDict:
    """One component per item kind, told apart by the `type` key."""
    refs: list[JsonDict] = []
    for kind, shape in sorted(variants.items()):
        name = 'Chunk' + ''.join(part.capitalize() for part in kind.split('_'))
        schema = object_schema(shape, f'{path}[]', components)
        properties = cast('JsonDict', schema['properties'])
        properties['type'] = {'type': 'string', 'const': kind}
        components[name] = schema
        refs.append(_ref(name))
    return {'oneOf': refs, 'discriminator': {'propertyName': 'type'}}


def _ref(name: str) -> JsonDict:
    return {'$ref': f'{_SCHEMAS}{name}'}


def _paths() -> JsonDict:
    blog = {
        'name': 'blog',
        'in': 'path',
        'required': True,
        'schema': {'type': 'string'},
    }
    return {
        '/blog/{blog}/post/': {
            'get': {
                'summary': 'A page of the blog posts, newest first',
                'parameters': [
                    blog,
                    {
                        'name': 'limit',
                        'in': 'query',
                        'schema': {'type': 'integer', 'maximum': 100},
                    },
                    {
                        'name': 'offset',
                        'in': 'query',
                        'description': 'The `extra.offset` of the previous page',
                        'schema': {'type': 'string'},
                    },
                ],
                'responses': {
                    '200': _json_response('PostsPage'),
                    '400': {'description': 'Malformed blog name'},
                    '401': {'description': 'Credentials rejected'},
                    '404': {'description': 'No such blog'},
                },
            }
        },
        '/blog/{blog}/post/{id}': {
            'get': {
                'summary': 'One post with fresh signed links',
                'parameters': [
                    blog,
                    {
                        'name': 'id',
                        'in': 'path',
                        'required': True,
                        'schema': {'type': 'string', 'format': 'uuid'},
                    },
                ],
                'responses': {
                    '200': _json_response('Post'),
                    '401': {'description': 'Credentials rejected'},
                    '404': {'description': 'No such post'},
                },
            }
        },
    }


def _json_response(schema_name: str) -> JsonDict:
    return {
        'description': 'OK',
        'content': {'application/json': {'schema': _ref(schema_name)}},
    }
