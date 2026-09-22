"""
Observed shapes of JSON answers: which keys came, how often, in which types.

The counts are all that is kept from an answer. Values are dropped, except
token-like strings of vocabulary fields (`type`, `uploadStatus`, ...), which
become the enum and x-seen-values lists of the schema. Free text, links and
ids never qualify as tokens.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import cast

# Arrays at these paths hold objects of several kinds told apart by `type`:
# every kind gets a shape of its own instead of one blend of all keys.
SPLIT_BY_TYPE: frozenset[str] = frozenset({'data'})
# Keys whose string values form a vocabulary worth listing in the schema.
VOCABULARY_KEY_SUFFIXES = (
    'type',
    'status',
    'modificator',
    'style',
    'currency',
    'rendition',
)
# A vocabulary value is one snake_case or CONSTANT_CASE token.
_TOKEN = re.compile(r'^(?:[a-z0-9_]+|[A-Z0-9_]+)$')
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_URI = re.compile(r'^https?://')
# Past this many distinct values a field is free text, not a vocabulary.
MAX_VOCABULARY_SIZE = 30


@dataclass
class FieldShape:
    """Everything seen at one key: how often it came and in which forms."""

    present: int = 0
    types: Counter[str] = field(default_factory=Counter[str])
    # Distinct token values of a vocabulary field; None once it proved free text.
    vocabulary: set[str] | None = field(default_factory=set[str])
    # Stay True while every string seen so far matched.
    uuid_like: bool = True
    uri_like: bool = True
    object: ObjectShape | None = None
    items: FieldShape | None = None
    # Item shapes of a split array, keyed by the item's `type`.
    variants: dict[str, ObjectShape] | None = None


@dataclass
class ObjectShape:
    """Every key seen in the objects at one place, over `samples` objects."""

    samples: int = 0
    fields: dict[str, FieldShape] = field(default_factory=dict[str, FieldShape])


# bool before int: a bool is an int in Python, not in JSON Schema.
_TYPE_NAMES: tuple[tuple[type, str], ...] = (
    (bool, 'boolean'),
    (int, 'integer'),
    (float, 'number'),
    (str, 'string'),
    (dict, 'object'),
    (list, 'array'),
)


def json_type(value: object) -> str:
    """Name the JSON Schema type of a decoded JSON value."""
    if value is None:
        return 'null'
    for python_type, name in _TYPE_NAMES:
        if isinstance(value, python_type):
            return name
    message = f'Not a JSON value: {type(value).__name__}'
    raise TypeError(message)


def observe(shape: ObjectShape, obj: dict[str, object], path: str = '') -> None:
    """Count one more object at `path` into `shape`, recursing into its values."""
    shape.samples += 1
    for key, value in obj.items():
        field_shape = shape.fields.setdefault(key, FieldShape())
        _observe_value(field_shape, value, f'{path}.{key}' if path else key)


def key_name(path: str) -> str:
    """Return the last key of a path: `data[].playerUrls[].type` -> `type`."""
    return path.rsplit('.', 1)[-1].removesuffix('[]')


def _observe_value(shape: FieldShape, value: object, path: str) -> None:
    shape.present += 1
    shape.types[json_type(value)] += 1
    if isinstance(value, str):
        _observe_string(shape, value, path)
    elif isinstance(value, dict):
        if shape.object is None:
            shape.object = ObjectShape()
        observe(shape.object, cast('dict[str, object]', value), path)
    elif isinstance(value, list):
        _observe_list(shape, cast('list[object]', value), path)


def _observe_string(shape: FieldShape, value: str, path: str) -> None:
    shape.uuid_like = shape.uuid_like and _UUID.match(value) is not None
    shape.uri_like = shape.uri_like and _URI.match(value) is not None
    if shape.vocabulary is None or not _is_vocabulary_key(path):
        return
    if _TOKEN.match(value) is None:
        shape.vocabulary = None
        return
    shape.vocabulary.add(value)
    if len(shape.vocabulary) > MAX_VOCABULARY_SIZE:
        shape.vocabulary = None


def _is_vocabulary_key(path: str) -> bool:
    return key_name(path).lower().endswith(VOCABULARY_KEY_SUFFIXES)


def _observe_list(shape: FieldShape, items: list[object], path: str) -> None:
    if path in SPLIT_BY_TYPE:
        if shape.variants is None:
            shape.variants = {}
        for item in items:
            kind = _kind_of(item, path)
            variant = shape.variants.setdefault(kind, ObjectShape())
            observe(variant, cast('dict[str, object]', item), f'{path}[]')
        return
    if shape.items is None:
        shape.items = FieldShape()
    for item in items:
        _observe_value(shape.items, item, f'{path}[]')


def _kind_of(item: object, path: str) -> str:
    """Return the `type` of an item in a split array; anything else is a shape error."""
    shape_name = json_type(item)
    if isinstance(item, dict):
        kind = cast('dict[str, object]', item).get('type')
        if isinstance(kind, str):
            return kind
    message = f'{path}[]: expected objects with a string "type", got {shape_name}'
    raise ValueError(message)
