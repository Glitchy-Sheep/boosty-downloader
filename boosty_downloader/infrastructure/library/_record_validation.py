"""Shared validation for values stored in library JSON records."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from re import Pattern
from re import compile as compile_pattern
from typing import TYPE_CHECKING, Final, cast

from boosty_downloader.domain.stored_post import PostMetadata

if TYPE_CHECKING:
    from collections.abc import Mapping

_ISO_DATETIME_PREFIX: Final = compile_pattern(r'^\d{4}-\d{2}-\d{2}[Tt ]')
_ISO_DURATION_PREFIX: Final = compile_pattern(r'^[+-]?P')
_DATETIME_FIELDS: Final = frozenset(
    {
        'created_at',
        'updated_at',
        'published_at',
        'first_downloaded_at',
        'synced_at',
        'added_at',
        'removed_at',
    }
)


def _require_iso_text(value: object, pattern: Pattern[str], name: str) -> None:
    if not isinstance(value, str) or not pattern.match(value):
        message = f'{name} must be an ISO8601 string'
        raise ValueError(message)


def validate_temporal_text(value: object) -> None:
    if not isinstance(value, dict):
        return
    fields = cast('Mapping[str, object]', value)
    for name, field in fields.items():
        if field is None:
            continue
        if name in _DATETIME_FIELDS:
            _require_iso_text(field, _ISO_DATETIME_PREFIX, name)
        elif name == 'duration':
            _require_iso_text(field, _ISO_DURATION_PREFIX, name)


def require_identity(value: str, name: str) -> None:
    if not value.strip():
        message = f'{name} must not be empty'
        raise ValueError(message)


def require_nonnegative(**values: float | None) -> None:
    for name, value in values.items():
        if value is not None and value < 0:
            message = f'{name} must not be negative'
            raise ValueError(message)


def as_utc(value: datetime, name: str) -> datetime:
    if value.utcoffset() is None:
        message = f'{name} must have a timezone'
        raise ValueError(message)
    try:
        return value.astimezone(timezone.utc)
    except OverflowError as error:
        message = f'{name} is outside the UTC datetime range'
        raise ValueError(message) from error


def optional_utc(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    return as_utc(value, name)


def validate_post_metadata(post: PostMetadata) -> PostMetadata:
    require_identity(post.id, 'id')
    require_identity(post.author, 'author')
    require_nonnegative(
        likes=post.likes,
        comments=post.comments,
        tier_price_rub=post.tier_price_rub,
        post_price_rub=post.post_price_rub,
    )
    require_nonnegative(**post.content_counters)
    return replace(
        post,
        created_at=as_utc(post.created_at, 'created_at'),
        updated_at=as_utc(post.updated_at, 'updated_at'),
        published_at=optional_utc(post.published_at, 'published_at'),
    )


def validate_relative_file_path(value: str | None, name: str) -> None:
    if value is None:
        return
    if (
        not value
        or '\\' in value
        or '\0' in value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(part in {'', '.', '..'} for part in value.split('/'))
    ):
        message = f'{name} must be a portable relative file path'
        raise ValueError(message)
