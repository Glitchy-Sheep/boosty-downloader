"""Rebuildable SQLite search projection of canonical library records."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, IntEnum
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Final

from sqlalchemy import MetaData, insert, inspect, select, text
from sqlalchemy.exc import DatabaseError, NoSuchTableError

from boosty_downloader.infrastructure.library._index_engine import (
    INDEX_SIDECAR_SUFFIXES,
    make_index_engine,
    validate_index_path,
)
from boosty_downloader.infrastructure.library._index_models import IndexBase, IndexMeta
from boosty_downloader.infrastructure.library._index_writes import (
    delete_post,
    refresh_author_counts,
    write_author,
    write_posts,
)
from boosty_downloader.infrastructure.library.index_projection import (
    project_author,
    project_post,
)
from boosty_downloader.infrastructure.library.index_sources import (
    scan_authors,
    scan_posts,
)
from boosty_downloader.infrastructure.library.library_format import (
    check_library_compatibility,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from sqlalchemy import Connection

    from boosty_downloader.infrastructure.library.index_projection import (
        AuthorProjection,
        PostProjection,
    )

INDEX_FILENAME: Final = 'index.db'
INDEX_SCHEMA_VERSION: Final = 1
_POST_BATCH_SIZE: Final = 100
_META_ROW_ID: Final = 1
_SQLITE_PRIMARY_CODE_MASK: Final = 0xFF
_FTS_CREATE_SQL: Final = (
    'CREATE VIRTUAL TABLE posts_fts USING fts5(title, body, original_title UNINDEXED, '
    "original_body UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
)


class IndexStatus(str, Enum):
    """Whether the disposable database can answer queries for this library."""

    current = 'current'
    missing = 'missing'
    incompatible = 'incompatible'
    corrupt = 'corrupt'


class IndexNotPreparedError(RuntimeError):
    """
    The connection belongs to another index version or canonical library root.

    Call ensure() explicitly to prepare this index before querying it.
    """


class _SQLiteErrorCode(IntEnum):
    corrupt = 11
    not_a_database = 26


@dataclass(frozen=True, slots=True)
class IndexBuildCounts:
    """Canonical authors and posts projected by a completed rebuild."""

    authors: int
    posts: int


@dataclass(frozen=True, slots=True)
class _IndexLocation:
    root: Path
    database: Path


class LibraryIndex:
    """
    A disposable index; construction opens no files or connections.

    Call ensure() at startup to check integrity. Incremental writes guard the
    version and source root without scanning all pages. New database corruption
    propagates to the caller until the next explicit ensure() repairs it.
    """

    def __init__(self, library_root: Path, *, index_path: Path | None = None) -> None:
        if index_path is not None and index_path.name != INDEX_FILENAME:
            message = f'The disposable index filename must be {INDEX_FILENAME}'
            raise ValueError(message)
        self._root = library_root
        self._index_path = index_path

    @property
    def path(self) -> Path:
        """Resolved database location without following the database itself."""
        if self._index_path is not None:
            return self._index_path.parent.resolve() / self._index_path.name
        return self._root.resolve() / '.boosty-downloader' / INDEX_FILENAME

    def status(self) -> IndexStatus:
        """Check schema, source root and integrity without repairing the database."""
        location = self._location()
        return _read_status(location)

    def ensure(self) -> IndexStatus:
        """Check integrity, rebuild if needed and return the initial index state."""
        location = self._location()
        status = _read_status(location)
        if status is not IndexStatus.current:
            self._rebuild(location, status)
        return status

    def rebuild(self) -> IndexBuildCounts:
        """Project every canonical record in one atomic database transaction."""
        location = self._location()
        return self._rebuild(location, _read_status(location))

    @contextmanager
    def connect(self) -> Generator[Connection]:
        """
        Open a read transaction guarded by the index version and source root.

        A missing database stays absent. An incompatible database raises
        IndexNotPreparedError; ensure() prepares it explicitly.
        """
        location = self._location()
        with _connection(location.database, writable=False) as connection:
            _require_current_metadata(connection, location.root)
            yield connection

    def upsert_author(self, author: AuthorProjection) -> None:
        """Update one author after its canonical record has been saved."""
        with self._write_connection() as connection:
            write_author(connection, author)

    def upsert_post(self, post: PostProjection) -> None:
        """Atomically update one post, including media, tags and search text."""
        with self._write_connection() as connection:
            write_posts(connection, [post])
            refresh_author_counts(connection, author=post.metadata.author)

    def remove_post(self, author: str, post_id: str) -> None:
        """Remove a vanished post from the disposable projection only."""
        with self._write_connection() as connection:
            delete_post(connection, author, post_id)
            refresh_author_counts(connection, author=author)

    @contextmanager
    def _write_connection(self) -> Generator[Connection]:
        location = self._location()
        if not location.database.exists():
            self._rebuild(location, IndexStatus.missing)
        with _connection(location.database, writable=True) as connection:
            if _metadata_status(connection, location.root) is IndexStatus.current:
                yield connection
                return
        self.ensure()
        with _connection(location.database, writable=True) as connection:
            _require_current_metadata(connection, location.root)
            yield connection

    def _location(self) -> _IndexLocation:
        root = self._root.resolve()
        check_library_compatibility(root)
        location = _IndexLocation(root, self.path)
        validate_index_path(location.database)
        return location

    def _rebuild(
        self, location: _IndexLocation, status: IndexStatus
    ) -> IndexBuildCounts:
        location.database.parent.mkdir(parents=True, exist_ok=True)
        validate_index_path(location.database)
        if status is IndexStatus.corrupt:
            return _replace_corrupt_index(location)
        return _build_index(location)


@contextmanager
def _connection(path: Path, *, writable: bool) -> Generator[Connection]:
    validate_index_path(path)
    engine = make_index_engine(path, writable=writable)
    try:
        with engine.begin() as connection:
            yield connection
    finally:
        engine.dispose()


def _read_status(location: _IndexLocation) -> IndexStatus:
    if not location.database.exists():
        return IndexStatus.missing
    try:
        with _connection(location.database, writable=False) as connection:
            if connection.scalar(text('PRAGMA quick_check')) != 'ok':
                return IndexStatus.corrupt
            return _schema_status(connection, location.root)
    except DatabaseError as error:
        if _is_corrupt_database(error):
            return IndexStatus.corrupt
        raise


def _schema_status(connection: Connection, root: Path) -> IndexStatus:
    inspector = inspect(connection)
    names = set(inspector.get_table_names())
    if not set(IndexBase.metadata.tables).union({'posts_fts'}).issubset(names):
        return IndexStatus.incompatible
    fts_sql = connection.scalar(
        text("SELECT sql FROM sqlite_master WHERE name='posts_fts'")
    )
    if fts_sql != _FTS_CREATE_SQL:
        return IndexStatus.incompatible
    for table in IndexBase.metadata.sorted_tables:
        columns = {column['name'] for column in inspector.get_columns(table.name)}
        if set(table.columns.keys()) != columns:
            return IndexStatus.incompatible
    return _identity_status(connection, root)


def _metadata_status(connection: Connection, root: Path) -> IndexStatus:
    try:
        columns = inspect(connection).get_columns(IndexMeta.__tablename__)
    except NoSuchTableError:
        return IndexStatus.incompatible
    if {column['name'] for column in columns} != set(
        IndexMeta.__table__.columns.keys()
    ):
        return IndexStatus.incompatible
    return _identity_status(connection, root)


def _require_current_metadata(connection: Connection, root: Path) -> None:
    if _metadata_status(connection, root) is not IndexStatus.current:
        message = 'Index version or library root changed; call ensure() before querying'
        raise IndexNotPreparedError(message)


def _identity_status(connection: Connection, root: Path) -> IndexStatus:
    row = connection.execute(
        select(IndexMeta.schema_version, IndexMeta.library_root).where(
            IndexMeta.id == _META_ROW_ID
        )
    ).one_or_none()
    if (
        row is None
        or row.schema_version != INDEX_SCHEMA_VERSION
        or row.library_root != str(root)
    ):
        return IndexStatus.incompatible
    return IndexStatus.current


def _is_corrupt_database(error: DatabaseError) -> bool:
    code = getattr(error.orig, 'sqlite_errorcode', None)
    if isinstance(code, int):
        return code & _SQLITE_PRIMARY_CODE_MASK in set(_SQLiteErrorCode)
    return str(error.orig) in {
        'file is not a database',
        'database disk image is malformed',
    }


def _build_index(location: _IndexLocation) -> IndexBuildCounts:
    with _connection(location.database, writable=True) as connection:
        _reset_schema(connection)
        authors, posts = 0, 0
        for author in scan_authors(location.root):
            write_author(connection, project_author(author))
            authors += 1
            projections = (
                project_post(post) for post in scan_posts(location.root, author)
            )
            for batch in _post_batches(projections):
                write_posts(connection, batch)
                posts += len(batch)
        refresh_author_counts(connection)
        connection.execute(
            insert(IndexMeta),
            {
                'id': _META_ROW_ID,
                'schema_version': INDEX_SCHEMA_VERSION,
                'library_root': str(location.root),
            },
        )
    return IndexBuildCounts(authors, posts)


def _reset_schema(connection: Connection) -> None:
    connection.execute(text('DROP TABLE IF EXISTS posts_fts'))
    previous = MetaData()
    previous.reflect(bind=connection)
    connection.execute(text('PRAGMA defer_foreign_keys=ON'))
    previous.drop_all(connection)
    IndexBase.metadata.create_all(connection)
    connection.execute(text(_FTS_CREATE_SQL))


def _post_batches(posts: Iterator[PostProjection]) -> Iterator[list[PostProjection]]:
    while batch := list(islice(posts, _POST_BATCH_SIZE)):
        yield batch


def _replace_corrupt_index(location: _IndexLocation) -> IndexBuildCounts:
    original = location.database.stat()
    with TemporaryDirectory(
        prefix='.index-rebuild-', dir=location.database.parent
    ) as directory:
        temporary = Path(directory) / INDEX_FILENAME
        counts = _build_index(_IndexLocation(location.root, temporary))
        validate_index_path(location.database)
        current = location.database.stat()
        if (
            original.st_ino != current.st_ino
            or original.st_dev != current.st_dev
            or original.st_mtime_ns != current.st_mtime_ns
            or original.st_size != current.st_size
        ):
            message = 'The index changed during corruption recovery; retry preparation'
            raise RuntimeError(message)
        for suffix in INDEX_SIDECAR_SUFFIXES:
            location.database.with_name(location.database.name + suffix).unlink(
                missing_ok=True
            )
        temporary.replace(location.database)
        return counts
