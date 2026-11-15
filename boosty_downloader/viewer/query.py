"""Strict query-string parsing shared by viewer post and media selections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, TypeVar

from pydantic import ValidationError

from boosty_downloader.domain.library import LibraryContentKind, PostOrder
from boosty_downloader.domain.library import PostFilters as LibraryPostFilters
from boosty_downloader.domain.library_media import LibraryMediaView
from boosty_downloader.domain.library_media import MediaFilters as LibraryMediaFilters
from boosty_downloader.viewer import api_models as api

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
_VIEWS: Final[dict[api.MediaView, LibraryMediaView]] = {
    'all': LibraryMediaView.all,
    'images': LibraryMediaView.image,
    'videos': LibraryMediaView.video,
    'audio': LibraryMediaView.audio,
    'files': LibraryMediaView.file,
}
_Filters = TypeVar('_Filters', api.PostFilters, api.MediaFilters)


def parse_post_filters(query: MultiMapping[str]) -> api.PostFilters:
    """Reject ambiguous keys; HTTP booleans use only the explicit 0/1 form."""
    return _parse_filters(query, api.PostFilters)


def parse_media_filters(query: MultiMapping[str]) -> api.MediaFilters:
    """Accept only the media screen's view, order and explicit boolean filters."""
    return _parse_filters(query, api.MediaFilters)


def _parse_filters(query: MultiMapping[str], model: type[_Filters]) -> _Filters:
    values: dict[str, str | bool] = {}
    for key, value in query.items():
        if key not in model.model_fields or key in values:
            message = 'Unknown or repeated query parameter.'
            raise InvalidQueryError(message)
        values[key] = _filter_value(key, value)
    try:
        return model.model_validate(values)
    except ValidationError as error:
        message = 'Invalid filters.'
        raise InvalidQueryError(message) from error


def _filter_value(key: str, value: str) -> str | bool:
    if key in _BOOLEAN_FILTERS:
        if value not in {'0', '1'}:
            message = 'Boolean filters must be 0 or 1.'
            raise InvalidQueryError(message)
        return value == '1'
    return value


def library_post_filters(filters: api.PostFilters) -> LibraryPostFilters:
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


def library_media_view(view: api.MediaView) -> LibraryMediaView:
    """Translate the media screen's plural names into domain view values."""
    return _VIEWS[view]


def library_media_filters(filters: api.MediaFilters) -> LibraryMediaFilters:
    """Keep media predicates separate from the selected view."""
    return LibraryMediaFilters(
        unseen_only=filters.unseen,
        favorites_only=filters.fav,
        order=PostOrder(filters.order),
    )
