"""Golden test: a real post's JSON maps to a pinned domain snapshot.

The fixture is a captured API response of one post (identifiers, urls and
texts replaced with fakes), extended with an audio chunk and an unknown-type
chunk. The snapshot pins the whole DTO-to-domain mapping, including what
lands in unknown_content. An intentional mapping change regenerates it:
UPDATE_GOLDEN=1 task test - then review the golden diff.
"""

from __future__ import annotations

import json
import os
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from boosty_downloader.src.application.filtering import BoostyOkVideoType
from boosty_downloader.src.application.mappers.post_mapper import (
    map_post_dto_to_domain,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_content import (
    collect_unknown_content,
)

FIXTURES = Path(__file__).parents[2] / 'fixtures'
FIXTURE_FILE = FIXTURES / 'single_post.json'
GOLDEN_FILE = FIXTURES / 'single_post_domain.json'


def _snapshot(value: object) -> object:
    """Turn the mapping result into plain JSON-friendly data, deterministically."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _snapshot(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, list | tuple):
        return [_snapshot(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted((_snapshot(item) for item in value), key=json.dumps)
    return value


def test_real_post_shape_maps_to_the_pinned_domain():
    """A silent mapping change becomes wrong or missing files on disk."""
    dto = PostDTO.model_validate(json.loads(FIXTURE_FILE.read_text(encoding='utf-8')))

    result = map_post_dto_to_domain(dto, BoostyOkVideoType.medium)

    snapshot = (
        json.dumps(_snapshot(result), ensure_ascii=False, indent=2, sort_keys=True)
        + '\n'
    )
    if os.environ.get('UPDATE_GOLDEN') == '1':
        GOLDEN_FILE.write_text(snapshot, encoding='utf-8')

    assert snapshot == GOLDEN_FILE.read_text(encoding='utf-8')
    # The fixture's unknown chunk must stay visible to the tolerant reader.
    assert [u.path for u in collect_unknown_content(dto)] == ['data[10].type']
