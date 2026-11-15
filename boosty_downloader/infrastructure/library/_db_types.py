"""Validated value codecs for canonical library database columns."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import TYPE_CHECKING

from pydantic import TypeAdapter
from sqlalchemy import DateTime, Float, Text
from sqlalchemy.types import TypeDecorator

from boosty_downloader.domain.stored_post import Block, PostMetadata
from boosty_downloader.infrastructure.library._post_json_blocks import (
    JsonBlock,
    decode_blocks,
    encode_blocks,
)
from boosty_downloader.infrastructure.library._record_validation import (
    validate_post_metadata,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect

_METADATA = TypeAdapter(PostMetadata)
_BLOCKS = TypeAdapter(list[JsonBlock])


class UTCDateTime(TypeDecorator[datetime]):
    """Normalize aware timestamps to UTC without losing microseconds."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            message = 'Library timestamps must be timezone-aware'
            raise ValueError(message)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class SavedMetadata(TypeDecorator[PostMetadata]):
    """Retain the saved overview independently of a newer access observation."""

    impl = Text
    cache_ok = True

    def process_bind_param(
        self,
        value: PostMetadata | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> str | None:
        if value is None:
            return None
        _validate_prices(value)
        normalized = validate_post_metadata(value)
        return _METADATA.dump_json(normalized, warnings='error').decode()

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> PostMetadata | None:
        if value is None:
            return None
        metadata = _METADATA.validate_json(value, strict=True)
        _validate_prices(metadata)
        return validate_post_metadata(metadata)


def _validate_prices(metadata: PostMetadata) -> None:
    for price in (metadata.tier_price_rub, metadata.post_price_rub):
        _finite_number(price)


def _finite_number(value: float | None) -> float | None:
    if value is not None and not isfinite(value):
        message = 'Library numeric values must be finite'
        raise ValueError(message)
    return value


class FiniteFloat(TypeDecorator[float]):
    """Reject NaN before SQLite can silently turn it into an unknown value."""

    impl = Float
    cache_ok = True

    def process_bind_param(
        self,
        value: float | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> float | None:
        return _finite_number(value)

    def process_result_value(
        self,
        value: float | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> float | None:
        return _finite_number(value)


class PostBlocks(TypeDecorator[list[Block]]):
    """Preserve tagged body structure and return independent domain values."""

    impl = Text
    cache_ok = True

    def process_bind_param(
        self,
        value: list[Block] | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> str | None:
        return (
            _BLOCKS.dump_json(encode_blocks(value)).decode()
            if value is not None
            else None
        )

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> list[Block] | None:
        return (
            decode_blocks(_BLOCKS.validate_json(value)) if value is not None else None
        )
