"""Strict query-string parsing shared by viewer post selections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from boosty_downloader.domain.library import LibraryContentKind, PostOrder
from boosty_downloader.domain.library import PostFilters as LibraryPostFilters
from boosty_downloader.viewer.api_models import PostFilters

if TYPE_CHECKING:
    from multidict import MultiMapping


class InvalidQueryError(ValueError):
    """A supplied filter is unknown, repeated or invalid."""


_BOOLEAN_FILTERS: Final = frozenset({'unseen', 'fav', 'locked', 'incomplete'})
_KINDS: Final = {
    'images': LibraryContentKind.image,
    'videos': LibraryContentKind.video,
    'files': LibraryContentKind.file,
    'audio': LibraryContentKind.audio,
}


def parse_post_filters(query: MultiMapping[str]) -> PostFilters:
    """Reject ambiguous keys; HTTP booleans use only the explicit 0/1 form."""
    values: dict[str, str | bool] = {}
    for key, value in query.items():
        if key not in PostFilters.model_fields or key in values:
            message = 'Unknown or repeated query parameter.'
            raise InvalidQueryError(message)
        values[key] = _filter_value(key, value)
    try:
        return PostFilters.model_validate(values)
    except ValidationError as error:
        message = 'Invalid post filters.'
        raise InvalidQueryError(message) from error


def _filter_value(key: str, value: str) -> str | bool:
    if key in _BOOLEAN_FILTERS:
        if value not in {'0', '1'}:
            message = 'Boolean filters must be 0 or 1.'
            raise InvalidQueryError(message)
        return value == '1'
    if key == 'tag' and not value:
        message = 'A tag filter must not be empty.'
        raise InvalidQueryError(message)
    return value


def library_post_filters(filters: PostFilters) -> LibraryPostFilters:
    """Map the HTTP vocabulary to storage-independent browsing filters."""
    kind = _KINDS[filters.kind] if filters.kind is not None else None
    return LibraryPostFilters(
        text=filters.q,
        kind=kind,
        unseen_only=filters.unseen,
        favorites_only=filters.fav,
        tag=filters.tag,
        locked_only=filters.locked,
        incomplete_only=filters.incomplete,
        order=PostOrder(filters.order),
    )
