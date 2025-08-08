"""Implementation of a post cache using SQLAlchemy + SQLite local database."""

from datetime import datetime
from pathlib import Path
from types import TracebackType

from sqlalchemy import String, create_engine, text
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from boosty_downloader.src.application.filtering import (
    DownloadContentTypeFilter,
)
from boosty_downloader.src.infrastructure.loggers.base import RichLogger


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class _PostCacheEntryModel(Base):
    """Internal sqlite table structure of the caching layer"""

    __tablename__ = 'post_cache'
    _Iso8601Datetime = str

    post_uuid: Mapped[str] = mapped_column(String, primary_key=True)

    # Flags to see which parts of the posts were downloaded and which are not.
    files_downloaded: Mapped[bool] = mapped_column(default=False, nullable=False)
    post_content_downloaded: Mapped[bool] = mapped_column(default=False, nullable=False)
    external_videos_downloaded: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )
    boosty_videos_downloaded: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )

    # Timestamp of the last update of the post.
    # Useful to determine if the post is outdated and needs to be re-downloaded even if some parts were downloaded before.
    #
    # Should be in ISO 8601 format (e.g., "2023-10-01T12:00:00Z").
    # because SQLite does not have a native tz-aware datetime type.
    last_updated_timestamp: Mapped[_Iso8601Datetime] = mapped_column(
        String, nullable=False
    )


class SQLitePostCache:
    """
    Post cache using SQLite with SQLAlchemy.

    Caches posts in a local SQLite database under a given directory.
    Automatically reinitializes the database if it's missing or corrupted.

    Caching mechanism is smart enough to determine which specific parts are up-to-date
    and which are not.
    """

    DEFAULT_CACHE_FILENAME = 'post_cache.db'

    def __enter__(self) -> 'SQLitePostCache':
        """Create a context manager for the SQLitePostCache."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Ensure that the database connection is closed when exiting the context."""
        self.close()

    def __init__(self, destination: Path, logger: RichLogger) -> None:
        """Make a connection with the SQLite database and create/init it if necessary."""
        self.logger = logger

        self.destination = destination
        self.db_file: Path = self.destination / self.DEFAULT_CACHE_FILENAME
        self.db_file.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f'sqlite:///{self.db_file}')
        Base.metadata.create_all(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session: Session = self.Session()
        self._dirty = False

    def _check_db_integrity(self) -> bool:
        """Check if post_cache table is available and the db itself is accessible."""
        try:
            # Ping the database to check if it's accessible
            self.session.execute(text('SELECT 1 FROM post_cache LIMIT 1'))
            # Ensure the expected schema (column names) is present; reinit if legacy schema is detected
            self.session.execute(text('SELECT post_uuid FROM post_cache LIMIT 1'))
        except (OperationalError, DatabaseError):
            return False
        else:
            return True

    def _reinitialize_db(self) -> None:
        """Reinitialize the database (recreate it from scratch) and recreate session."""
        self.session.close()
        self.engine.dispose()

        if self.db_file.exists():
            self.db_file.unlink()  # Remove the corrupted file

        self.engine = create_engine(f'sqlite:///{self.db_file}')
        Base.metadata.create_all(self.engine)
        self.session = self.Session()

    def _ensure_valid(self) -> None:
        """Maintenance method to ensure the database is valid before use."""
        if not self._check_db_integrity():
            self.logger.error(
                'Post cache database is corrupted or inaccessible. Reinitializing...'
            )
            self._reinitialize_db()

    def commit(self) -> None:
        """
        Commit any pending changes to the database if there are modifications.

        This method should be called after making changes to the database (e.g., adding,
        updating, or deleting records) to ensure that the changes are persisted.
        The `_dirty` flag is used to track whether there are uncommitted changes.
        """
        if self._dirty:
            self.session.commit()
            self._dirty = False

    def cache(
        self,
        post_uuid: str,
        updated_at: datetime,
        was_downloaded: list[DownloadContentTypeFilter],
    ) -> None:
        """Cache a post by its UUID and updated_at timestamp."""
        self._ensure_valid()

        entry = self.session.get(_PostCacheEntryModel, post_uuid)

        files_downloaded = DownloadContentTypeFilter.files in was_downloaded
        boosty_videos_downloaded = (
            DownloadContentTypeFilter.boosty_videos in was_downloaded
        )
        post_content_downloaded = (
            DownloadContentTypeFilter.post_content in was_downloaded
        )
        external_videos_downloaded = (
            DownloadContentTypeFilter.external_videos in was_downloaded
        )

        # If post already existed - just update False fields to True.
        if entry:
            entry.last_updated_timestamp = updated_at.isoformat()
            entry.files_downloaded = files_downloaded or entry.files_downloaded
            entry.boosty_videos_downloaded = (
                boosty_videos_downloaded or entry.boosty_videos_downloaded
            )
            entry.post_content_downloaded = (
                post_content_downloaded or entry.post_content_downloaded
            )
            entry.external_videos_downloaded = (
                external_videos_downloaded or entry.external_videos_downloaded
            )
        else:
            entry = _PostCacheEntryModel(
                post_uuid=post_uuid,
                last_updated_timestamp=updated_at.isoformat(),
                files_downloaded=files_downloaded,
                boosty_videos_downloaded=boosty_videos_downloaded,
                post_content_downloaded=post_content_downloaded,
                external_videos_downloaded=external_videos_downloaded,
            )
            self.session.add(entry)

        self._dirty = True

    def get_missing_parts(
        self,
        post_uuid: str,
        updated_at: datetime,
        required: list[DownloadContentTypeFilter],
    ) -> list[DownloadContentTypeFilter]:
        """
        Determine which parts of the post still need to be downloaded.

        Returns all required parts if the post is missing or outdated; otherwise, returns only those parts that haven't been
        downloaded yet based on the current cache state.
        """
        self._ensure_valid()
        post = self.session.get(_PostCacheEntryModel, post_uuid)
        if not post:
            return required

        # If cached post is outdated in general, just mark all required parts as missing.
        if datetime.fromisoformat(post.last_updated_timestamp) < updated_at:
            return required

        missing: list[DownloadContentTypeFilter] = [
            part
            for part in required
            if (
                (part is DownloadContentTypeFilter.files and not post.files_downloaded)
                or (
                    part is DownloadContentTypeFilter.boosty_videos
                    and not post.boosty_videos_downloaded
                )
                or (
                    part is DownloadContentTypeFilter.external_videos
                    and not post.external_videos_downloaded
                )
                or (
                    part is DownloadContentTypeFilter.post_content
                    and not post.post_content_downloaded
                )
            )
        ]

        return missing

    def remove_cache_completely(self) -> None:
        """Reinitialize the cache completely in case if user wants to start fresh."""
        self._reinitialize_db()

    def close(self) -> None:
        """Save and close the database connection."""
        self.commit()
        self.session.close()
        self.engine.dispose()
