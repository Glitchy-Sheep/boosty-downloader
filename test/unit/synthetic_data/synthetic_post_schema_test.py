"""
The synthetic post looks like what Boosty really sends.

docs/api/boosty-api.yaml is the observed shape of the live API. Every key of
the synthetic post must exist there with the observed type and values, so
test data cannot drift into a shape Boosty never sends. Keys the schema calls
required may be missing: the post carries only what the client reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from support.synthetic_post import synthetic_post, unknown_chunk

SCHEMA_FILE = Path(__file__).parents[3] / 'docs' / 'api' / 'boosty-api.yaml'


def _strict(node: Any) -> Any:  # noqa: ANN401 - walks arbitrary schema JSON
    """Forbid keys the schema does not list; drop what the sample always had."""
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    strict = {key: _strict(value) for key, value in node.items() if key != 'required'}
    if 'properties' in strict:
        strict['additionalProperties'] = False
    return strict


def _components() -> dict[str, Any]:
    return yaml.safe_load(SCHEMA_FILE.read_text(encoding='utf-8'))['components']


def _validator(component: str) -> Draft202012Validator:
    schema = {
        '$ref': f'#/components/schemas/{component}',
        'components': _strict(_components()),
    }
    return Draft202012Validator(schema)


def _errors(validator: Draft202012Validator, instance: object) -> list[str]:
    return [
        f'{error.json_path}: {error.message}'
        for error in validator.iter_errors(instance)
    ]


def test_synthetic_post_matches_the_observed_schema():
    """A made-up key or type in test data hides a model that reads the wrong thing."""
    post = synthetic_post()
    post['data'] = [chunk for chunk in post['data'] if chunk != unknown_chunk()]

    errors = _errors(_validator('Post'), post)

    assert not errors, 'Synthetic post differs from the schema:\n' + '\n'.join(errors)


def test_unknown_chunk_is_unknown_to_the_schema():
    """The tolerant-reader tests need a chunk type Boosty has never sent."""
    chunk_kinds = [
        name for name in _components()['schemas'] if name.startswith('Chunk')
    ]

    matches = [
        name for name in chunk_kinds if not _errors(_validator(name), unknown_chunk())
    ]

    assert not matches, f'The schema now knows the "unknown" chunk: {matches}'
