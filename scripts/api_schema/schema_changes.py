"""
What the live API sends that docs/api/boosty-api.yaml does not know yet.

Compares a schema built from fresh answers with the committed one. Only
additions count: a chunk kind, a key, a type or a vocabulary value the
committed schema lacks. A key absent from the fresh answers says nothing:
one page of one blog rarely holds every key. A change that breaks the
client fails the canary tests instead; these changes break nothing yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

JsonDict = dict[str, object]
ChangeKind = Literal['new_chunk', 'new_key', 'new_type', 'new_value']


@dataclass(frozen=True, slots=True)
class SchemaChange:
    """One addition, e.g. `new_value` at `ChunkOkVideo.status` with `processing`."""

    kind: ChangeKind
    where: str
    detail: str


def find_changes(committed: JsonDict, live: JsonDict) -> list[SchemaChange]:
    """List what `live` has and `committed` does not, component by component."""
    known = _schemas(committed)
    changes: list[SchemaChange] = []
    for name, schema in _schemas(live).items():
        if name in known:
            changes += _object_changes(known[name], schema, name)
        elif name.startswith('Chunk'):
            changes.append(SchemaChange('new_chunk', name, _chunk_kind(schema)))
    return changes


def _schemas(document: JsonDict) -> dict[str, JsonDict]:
    components = cast('JsonDict', document['components'])
    return cast('dict[str, JsonDict]', components['schemas'])


def _chunk_kind(schema: JsonDict) -> str:
    """Return the `type` value that names a chunk kind, e.g. `poll`."""
    kind = _properties(schema).get('type', {})
    return str(kind.get('const', ''))


def _properties(schema: JsonDict) -> dict[str, JsonDict]:
    return cast('dict[str, JsonDict]', schema.get('properties', {}))


def _object_changes(
    committed: JsonDict, live: JsonDict, where: str
) -> list[SchemaChange]:
    known = _properties(committed)
    changes: list[SchemaChange] = []
    for key, schema in _properties(live).items():
        path = f'{where}.{key}'
        if key in known:
            changes += _key_changes(known[key], schema, path)
        else:
            changes.append(SchemaChange('new_key', path, type_text(schema)))
    return changes


def _key_changes(committed: JsonDict, live: JsonDict, where: str) -> list[SchemaChange]:
    changes: list[SchemaChange] = []
    if _types(live) - _types(committed):
        detail = f'{type_text(committed)} → {type_text(live)}'
        changes.append(SchemaChange('new_type', where, detail))
    changes += [
        SchemaChange('new_value', where, value)
        for value in sorted(_values(live) - _values(committed))
    ]
    changes += _object_changes(committed, live, where)
    items, known_items = live.get('items'), committed.get('items')
    # Chunk lists point at components through oneOf: those are compared on their own.
    if (
        isinstance(items, dict)
        and isinstance(known_items, dict)
        and 'oneOf' not in items
    ):
        changes += _key_changes(
            cast('JsonDict', known_items), cast('JsonDict', items), f'{where}[]'
        )
    return changes


def _types(schema: JsonDict) -> set[str]:
    types = schema.get('type', [])
    return {types} if isinstance(types, str) else set(cast('list[str]', types))


def type_text(schema: JsonDict) -> str:
    """Write the type the way the schema does, e.g. `integer|null`."""
    return '|'.join(sorted(_types(schema)))


def _values(schema: JsonDict) -> set[str]:
    listed = cast(
        'list[str]', schema.get('enum', []) or schema.get('x-seen-values', [])
    )
    return set(listed)
