"""Generic search for unknown content in parsed API models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Sequence

from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_unknown import (
    BoostyPostDataUnknownDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_value import (
    BoostyUnknownValue,
)


@dataclass(frozen=True, slots=True)
class UnknownContent:
    """A value the client doesn't know yet: where it sits and what came."""

    path: str
    raw: str


def collect_unknown_content(model: BaseModel) -> set[UnknownContent]:
    """
    Find every unknown value anywhere in a parsed model tree.

    Tolerant fields parse unknown input into BoostyUnknownValue and unknown
    chunks into BoostyPostDataUnknownDTO, so one type-driven walk reports
    them all. There is no per-field registry to keep in sync: a new tolerant
    field is discovered automatically.
    """
    found: set[UnknownContent] = set()
    _walk(model, '', found)
    return found


def _walk(value: object, path: str, found: set[UnknownContent]) -> None:
    if isinstance(value, BoostyUnknownValue):
        found.add(UnknownContent(path=path, raw=value.raw))
        return
    if isinstance(value, BoostyPostDataUnknownDTO):
        found.add(UnknownContent(path=_join(path, 'type'), raw=value.type))
        return
    if isinstance(value, BaseModel):
        for name, field_info in type(value).model_fields.items():
            child_path = _join(path, field_info.alias or name)
            _walk(getattr(value, name), child_path, found)
        return
    if isinstance(value, (list, tuple)):
        items = cast('Sequence[object]', value)
        for index, item in enumerate(items):
            _walk(item, f'{path}[{index}]', found)
        return
    # Scalars (str, Enum, None, numbers) can't contain unknown content.


def _join(path: str, name: str) -> str:
    return f'{path}.{name}' if path else name
