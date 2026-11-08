"""Typed tables for the disposable library projection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect


class UTCDateTime(TypeDecorator[datetime]):
    """Store UTC values and restore timezone awareness after SQLite reads."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            message = 'Index timestamps must be timezone-aware'
            raise ValueError(message)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002 - SQLAlchemy type hook
    ) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class IndexBase(DeclarativeBase):
    """Metadata owned exclusively by the rebuildable index."""


class IndexMeta(IndexBase):
    """The single completed index format and canonical source root."""

    __tablename__ = 'meta'

    id: Mapped[int] = mapped_column(primary_key=True)
    schema_version: Mapped[int]
    library_root: Mapped[str]


class IndexAuthor(IndexBase):
    """Author metadata and source versions, independent of post folder existence."""

    __tablename__ = 'authors'

    author: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str | None]
    owner_name: Mapped[str | None]
    description: Mapped[str | None]
    avatar_path: Mapped[str | None]
    cover_path: Mapped[str | None]
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    remote_post_count: Mapped[int | None]
    post_count: Mapped[int] = mapped_column(default=0)
    locked_post_count: Mapped[int] = mapped_column(default=0)
    author_json_mtime_ns: Mapped[int | None]
    author_json_size: Mapped[int | None]
    locked_json_mtime_ns: Mapped[int | None]
    locked_json_size: Mapped[int | None]


class IndexPost(IndexBase):
    """Current overview plus retained content, search and viewing projections."""

    __tablename__ = 'posts'
    __table_args__ = (
        UniqueConstraint('author', 'post_id'),
        Index('ix_posts_author_created', 'author', 'created_at'),
        Index('ix_posts_author_access', 'author', 'access'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    author: Mapped[str] = mapped_column(
        ForeignKey('authors.author', ondelete='CASCADE')
    )
    post_id: Mapped[str]
    folder: Mapped[str | None]
    url: Mapped[str]
    title: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    access: Mapped[str]
    origin: Mapped[str]
    tier: Mapped[str | None]
    tier_price_rub: Mapped[float | None]
    post_price_rub: Mapped[float | None]
    likes: Mapped[int]
    comments: Mapped[int]
    content_counters: Mapped[dict[str, int]] = mapped_column(JSON)
    current_counts: Mapped[dict[str, int]] = mapped_column(JSON)
    downloaded_counts: Mapped[dict[str, int]] = mapped_column(JSON)
    cover_path: Mapped[str | None]
    teaser_path: Mapped[str | None]
    excerpt: Mapped[str]
    pieces_added_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    favorite: Mapped[bool]
    post_json_mtime_ns: Mapped[int | None]
    post_json_size: Mapped[int | None]
    viewer_json_mtime_ns: Mapped[int | None]
    viewer_json_size: Mapped[int | None]


class IndexPostTag(IndexBase):
    """A distinct tag of one indexed full-identity post."""

    __tablename__ = 'post_tags'
    __table_args__ = (Index('ix_post_tags_tag_post', 'tag', 'post_row_id'),)

    post_row_id: Mapped[int] = mapped_column(
        ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True
    )
    tag: Mapped[str] = mapped_column(primary_key=True)


class IndexMedia(IndexBase):
    """Post-local media history; file and thumbnail paths are library-relative."""

    __tablename__ = 'media'
    __table_args__ = (
        Index('ix_media_storage', 'status', 'author', 'kind', 'size'),
        Index('ix_media_post_order', 'post_row_id', 'position'),
    )

    author: Mapped[str] = mapped_column(primary_key=True)
    post_id: Mapped[str] = mapped_column(primary_key=True)
    media_id: Mapped[str] = mapped_column(primary_key=True)
    post_row_id: Mapped[int] = mapped_column(ForeignKey('posts.id', ondelete='CASCADE'))
    kind: Mapped[str]
    status: Mapped[str]
    position: Mapped[int]
    path: Mapped[str | None]
    thumbnail_path: Mapped[str | None]
    preview_path: Mapped[str | None]
    title: Mapped[str | None]
    filename: Mapped[str | None]
    artist: Mapped[str | None]
    size: Mapped[int | None]
    duration: Mapped[float | None]
    width: Mapped[int | None]
    height: Mapped[int | None]
    added_at: Mapped[datetime] = mapped_column(UTCDateTime)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    playback_position: Mapped[float | None]
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
