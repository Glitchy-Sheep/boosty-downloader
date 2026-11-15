"""Canonical records; access observations never replace saved content or marks."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves mapped annotations
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.stored_post import (
    Block,
    MediaKind,
    MediaStatus,
    PostMetadata,
)
from boosty_downloader.infrastructure.library._db_types import (
    FiniteFloat,
    PostBlocks,
    SavedMetadata,
    UTCDateTime,
)
from boosty_downloader.infrastructure.library._post_text import fold_search_text

if TYPE_CHECKING:
    from sqlalchemy import Connection
    from sqlalchemy.orm import Mapper


class LibraryBase(DeclarativeBase):
    """Metadata for the primary store, independent of the disposable JSON index."""


class DbMeta(LibraryBase):
    """One schema version and portable identity for the primary library."""

    __tablename__ = 'meta'
    __table_args__ = (CheckConstraint('id = 1'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schema_version: Mapped[int]
    library_id: Mapped[str]


class DbAuthor(LibraryBase):
    """An author identity can exist before blog metadata becomes available."""

    __tablename__ = 'authors'
    __table_args__ = (CheckConstraint('remote_post_count >= 0'),)

    author: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str | None]
    owner_name: Mapped[str | None]
    description: Mapped[str | None]
    avatar_path: Mapped[str | None]
    cover_path: Mapped[str | None]
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    remote_post_count: Mapped[int | None]


class DbPost(LibraryBase):
    """The latest overview and optional retained saved post, with separate clocks."""

    __tablename__ = 'posts'
    __table_args__ = (
        UniqueConstraint('author', 'post_id'),
        UniqueConstraint('id', 'author'),
        CheckConstraint("origin IS NULL OR origin = 'api'"),
        CheckConstraint('likes >= 0 AND comments >= 0'),
        CheckConstraint('tier_price_rub >= 0 AND post_price_rub >= 0'),
        CheckConstraint('page_template >= 0'),
        CheckConstraint(
            '(saved_metadata IS NULL AND folder IS NULL AND blocks_json IS NULL '
            'AND origin IS NULL AND first_downloaded_at IS NULL AND synced_at IS NULL '
            'AND page_template IS NULL) OR '
            '(saved_metadata IS NOT NULL AND folder IS NOT NULL AND blocks_json IS NOT NULL '
            "AND origin = 'api' AND first_downloaded_at IS NOT NULL AND synced_at IS NOT NULL)"
        ),
        CheckConstraint(
            "(access = 'locked' AND locked_synced_at IS NOT NULL) OR "
            "(access = 'open' AND locked_synced_at IS NULL AND saved_metadata IS NOT NULL)"
        ),
        Index('ix_posts_author_created', 'author', 'created_at'),
        Index('ix_posts_author_access', 'author', 'access'),
        Index('ix_posts_author_folder', 'author', 'folder'),
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
    access: Mapped[PostAccess] = mapped_column(Enum(PostAccess, create_constraint=True))
    tier: Mapped[str | None]
    tier_price_rub: Mapped[float | None] = mapped_column(FiniteFloat)
    post_price_rub: Mapped[float | None] = mapped_column(FiniteFloat)
    likes: Mapped[int] = mapped_column(default=0)
    comments: Mapped[int] = mapped_column(default=0)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_counters: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    saved_metadata: Mapped[PostMetadata | None] = mapped_column(SavedMetadata)
    blocks: Mapped[list[Block] | None] = mapped_column('blocks_json', PostBlocks)
    origin: Mapped[str | None]
    first_downloaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    page_template: Mapped[int | None]
    locked_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    teaser_path: Mapped[str | None]
    teaser_thumbnail_path: Mapped[str | None]
    body_text: Mapped[str] = mapped_column(default='')
    title_search: Mapped[str] = mapped_column(default='')
    body_search: Mapped[str] = mapped_column(default='')


class DbMedia(LibraryBase):
    """Post-local media history with canonical relative path bases."""

    __tablename__ = 'media'
    __table_args__ = (
        ForeignKeyConstraint(
            ['post_row_id', 'author'], ['posts.id', 'posts.author'], ondelete='CASCADE'
        ),
        CheckConstraint('position >= 0 AND size >= 0 AND duration >= 0'),
        CheckConstraint('width >= 0 AND height >= 0'),
        CheckConstraint(
            "status != 'downloaded' OR (path IS NOT NULL AND size IS NOT NULL)"
        ),
        Index('ix_media_storage', 'status', 'author', 'kind', 'size'),
        Index('ix_media_post_order', 'post_row_id', 'position'),
    )

    post_row_id: Mapped[int] = mapped_column(primary_key=True)
    media_id: Mapped[str] = mapped_column(primary_key=True)
    author: Mapped[str]
    kind: Mapped[MediaKind] = mapped_column(Enum(MediaKind, create_constraint=True))
    status: Mapped[MediaStatus] = mapped_column(
        Enum(MediaStatus, create_constraint=True)
    )
    position: Mapped[int]
    path: Mapped[str | None]
    thumbnail_path: Mapped[str | None]
    preview_path: Mapped[str | None]
    title: Mapped[str | None]
    filename: Mapped[str | None]
    artist: Mapped[str | None]
    size: Mapped[int | None]
    duration: Mapped[float | None] = mapped_column(FiniteFloat)
    width: Mapped[int | None]
    height: Mapped[int | None]
    error: Mapped[str | None]
    added_at: Mapped[datetime] = mapped_column(UTCDateTime)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class DbPostTag(LibraryBase):
    """Distinct effective overview tags for indexed membership queries."""

    __tablename__ = 'post_tags'
    __table_args__ = (Index('ix_post_tags_tag_post', 'tag', 'post_row_id'),)

    post_row_id: Mapped[int] = mapped_column(
        ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True
    )
    tag: Mapped[str] = mapped_column(primary_key=True)


class DbMarks(LibraryBase):
    """User marks survive downloader changes to saved content and access."""

    __tablename__ = 'marks'

    post_row_id: Mapped[int] = mapped_column(
        ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True
    )
    seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    favorite: Mapped[bool] = mapped_column(default=False)


class DbMediaMarks(LibraryBase):
    """Playback positions survive removed or unknown media inventory entries."""

    __tablename__ = 'media_marks'
    __table_args__ = (CheckConstraint('position >= 0'),)

    post_row_id: Mapped[int] = mapped_column(
        ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True
    )
    media_id: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[float] = mapped_column(FiniteFloat)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


@event.listens_for(DbPost, 'before_insert')
@event.listens_for(DbPost, 'before_update')
def _prepare_search(
    _mapper: Mapper[DbPost], _connection: Connection, post: DbPost
) -> None:
    post.title_search = fold_search_text(post.title)
    post.body_search = fold_search_text(post.body_text or '')
