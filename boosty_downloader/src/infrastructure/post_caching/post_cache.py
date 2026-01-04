"""Implementation of a post cache using SQLAlchemy + SQLite local database."""

from datetime import datetime
from pathlib import Path
from types import TracebackType

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from boosty_downloader.src.application.filtering import DownloadContentTypeFilter
from boosty_downloader.src.infrastructure.loggers.base import RichLogger

from .migrations import apply_migrations
from .models import Base, PostCacheEntryModel


class SQLitePostCache:
    """
    Post cache using SQLite with SQLAlchemy.

    Caches posts in a local SQLite database under a given directory.
    Automatically reinitializes the database if it's missing or corrupted.

    Caching mechanism is smart enough to determine which specific parts are up-to-date
    and which are not.

    If the database doesn't exist, it will be created with all needed migrations applied.
    But if the end user modify something by hand - the database will be reinitialized (considering it's corrupted).
    """

    DEFAULT_CACHE_FILENAME = 'post_cache.db'

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def __init__(self, destination: Path, logger: RichLogger) -> None:
        """Make a connection with the SQLite database and create/init it if necessary."""
        self._logger = logger
        self._destination = destination
        self._db_file: Path = self._destination / self.DEFAULT_CACHE_FILENAME
        self._db_file.parent.mkdir(parents=True, exist_ok=True)

        self._engine = create_engine(f'sqlite:///{self._db_file}')
        self._session_maker = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._session: Session = self._session_maker()
        self._dirty = False

        apply_migrations(self._engine, self._session)

        if not self._schema_matches_model():
            self._logger.error(
                'Post cache database is corrupted or inaccessible. Reinitializing...'
            )
            self._reinitialize_db()

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

    def close(self) -> None:
        """Save and close the database connection."""
        self.commit()
        self._session.close()
        self._engine.dispose()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def commit(self) -> None:
        """
        Commit any pending changes to the database if there are modifications.

        This method should be called after making changes to the database (e.g., adding,
        updating, or deleting records) to ensure that the changes are persisted.
        The `_dirty` flag is used to track whether there are uncommitted changes.
        """
        if self._dirty:
            self._session.commit()
            self._dirty = False

    def cache_post(
        self,
        post_uuid: str,
        updated_at: datetime,
        was_downloaded: list[DownloadContentTypeFilter],
    ) -> None:
        """Cache a post by its UUID and updated_at timestamp."""
        entry = self._session.get(PostCacheEntryModel, post_uuid)

        if entry:
            entry.last_updated_timestamp = updated_at.isoformat()
            entry.mark_downloaded(was_downloaded)
        else:
            entry = PostCacheEntryModel.create_new(
                post_uuid, updated_at, was_downloaded
            )
            self._session.add(entry)

        self._dirty = True

    def get_post_missing_parts(
        self,
        post_uuid: str,
        updated_at: datetime,
        required: list[DownloadContentTypeFilter],
    ) -> list[DownloadContentTypeFilter]:
        """
        Determine which parts of the post still need to be downloaded.

        Returns all required parts if the post is missing or outdated; otherwise,
        returns only those parts that haven't been downloaded yet based on the
        current cache state.
        """
        post = self._session.get(PostCacheEntryModel, post_uuid)
        if not post:
            return required

        # If cached post is outdated, mark all required parts as missing
        if datetime.fromisoformat(post.last_updated_timestamp) < updated_at:
            return required

        return [part for part in required if not post.is_downloaded(part)]

    def remove_cache_completely(self) -> None:
        """Reinitialize the cache completely in case if user wants to start fresh."""
        self._reinitialize_db()

    # -------------------------------------------------------------------------
    # Private: Database health
    # -------------------------------------------------------------------------

    def _schema_matches_model(self) -> bool:
        """Check if the database schema has all columns defined in the model."""
        try:
            inspector = inspect(self._engine)
            existing = {col['name'] for col in inspector.get_columns('post_cache')}
            expected = {c.name for c in PostCacheEntryModel.__table__.columns}
            return expected.issubset(existing)
        except (OperationalError, DatabaseError):
            return False

    def _reinitialize_db(self) -> None:
        """Reinitialize the database (recreate it from scratch) and recreate session."""
        self._session.close()
        self._engine.dispose()

        if self._db_file.exists():
            self._db_file.unlink()

        self._engine = create_engine(f'sqlite:///{self._db_file}')
        Base.metadata.create_all(self._engine)
        self._session = self._session_maker()

        apply_migrations(self._engine, self._session)
