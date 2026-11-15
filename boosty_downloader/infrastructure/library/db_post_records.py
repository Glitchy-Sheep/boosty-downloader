"""Store detached saved posts in the primary library, without JSON side effects."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import delete, select

from boosty_downloader.domain.library import LocatedPost, PostAccess
from boosty_downloader.domain.post_folder import (
    compose_post_directory_name,
    get_post_id_prefix,
    parse_post_folder_id,
)
from boosty_downloader.infrastructure.library._db_models import (
    DbMarks,
    DbMedia,
    DbMediaMarks,
    DbPost,
)
from boosty_downloader.infrastructure.library._db_post_mapping import (
    read_saved_post,
    update_media_entry,
    update_saved_post,
)
from boosty_downloader.infrastructure.library._db_post_paths import (
    CreatedPostDirectories,
    author_directory,
    canonical_post_folder,
    directory_exists,
    path_is_occupied,
    portable_path_key,
)
from boosty_downloader.infrastructure.library._db_records import (
    ensure_author,
    find_post_row,
    read_session,
    require_author_identity,
    synchronize_post_tags,
)
from boosty_downloader.infrastructure.library._stored_validation import (
    validate_stored_post,
    validation_message,
)
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidPostRecordError,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Generator
    from pathlib import Path

    from sqlalchemy.orm import Session

    from boosty_downloader.domain.stored_post import PostMetadata, StoredPost
    from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


class DatabasePostRecords:
    """
    Saved-post operations for a caller-owned, initialized primary database.

    Folder paths normalize to their canonical library-relative location within the same author's post layout. Lookup and choice never create folders or write rows.

    A missing post folder is created only after its new database generation commits. A publication failure leaves that generation hidden until a later save retries; it cannot expose the previous generation or its marks through a recreated folder.
    """

    def __init__(self, root: Path, database: LibraryDatabase) -> None:
        self._root = root.resolve()
        self._database = database

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Find the full identity first, then a single unowned id8 folder."""
        prefix = get_post_id_prefix(post_id)
        author_folder = author_directory(self._root, author)
        with self._read_session() as session:
            require_author_identity(session, author)
            row = find_post_row(session, author, post_id)
            if row is not None and (located := self._read_saved(session, row)):
                return located
            return self._find_unowned(session, author_folder, post_id, prefix)

    def choose_post_folder(
        self,
        post: PostMetadata,
        *,
        reserved_folders: Collection[str] = (),
    ) -> str:
        """Suggest an unoccupied path without changing the filesystem or database."""
        author_folder = author_directory(self._root, post.author)
        reserved = {portable_path_key(folder) for folder in reserved_folders}
        collision = 0
        with self._read_session() as session:
            require_author_identity(session, post.author)
            while True:
                name = compose_post_directory_name(
                    post.title,
                    post.created_at,
                    post.id,
                    collision=collision,
                )
                relative = f'{post.author}/{name}'
                if (
                    portable_path_key(relative) not in reserved
                    and not path_is_occupied(author_folder / name)
                    and not _foreign_owner(session, relative, post.author, post.id)
                ):
                    return relative
                collision += 1

    def save_post(self, folder: str, record: StoredPost) -> None:
        """Commit one complete saved snapshot while preserving independent marks."""
        record = validate_stored_post(record)
        with CreatedPostDirectories() as directories:
            target = self._save_snapshot(folder, record, directories)
            if target is not None:
                canonical = target.relative_to(self._root).as_posix()
                _require_canonical_folder(self._root, canonical, record.post)
                target.mkdir()
                _require_canonical_folder(self._root, canonical, record.post)

    def _save_snapshot(
        self,
        folder: str,
        record: StoredPost,
        directories: CreatedPostDirectories,
    ) -> Path | None:
        with self._database.transaction() as session:
            require_author_identity(session, record.post.author)
            canonical = canonical_post_folder(
                self._root, folder, record.post.author, record.post.id
            )
            row = self._prepare_row(session, canonical, record)
            target = self._root / canonical
            publish = not directory_exists(target)
            directories.create(target.parent)
            _require_canonical_folder(self._root, canonical, record.post)
            update_saved_post(row, canonical, record)
            session.flush()
            _update_inventory(session, row, record)
            synchronize_post_tags(session, row)
        return target if publish else None

    @contextmanager
    def _read_session(self) -> Generator[Session, None, None]:
        try:
            with read_session(self._database) as session:
                yield session
        except ValidationError as error:
            raise InvalidPostRecordError(validation_message(error)) from None

    def _saved_folder(self, row: DbPost) -> str | None:
        if row.folder is None:
            return None
        canonical = canonical_post_folder(
            self._root, row.folder, row.author, row.post_id
        )
        if canonical != row.folder:
            message = (
                f'Saved post folder redirects its canonical location: {row.folder}'
            )
            raise ValueError(message)
        if not directory_exists(self._root / canonical):
            return None
        return canonical

    def _read_saved(self, session: Session, row: DbPost) -> LocatedPost | None:
        folder = self._saved_folder(row)
        if folder is None:
            return None
        _require_ownership(session, folder, row.author, row.post_id)
        media = list(
            session.scalars(
                select(DbMedia)
                .where(DbMedia.post_row_id == row.id)
                .order_by(DbMedia.position, DbMedia.media_id)
            )
        )
        return LocatedPost(folder, read_saved_post(row, media))

    def _find_unowned(
        self,
        session: Session,
        author_folder: Path,
        post_id: str,
        prefix: str,
    ) -> LocatedPost | None:
        if not directory_exists(author_folder):
            return None
        candidates: set[str] = set()
        for path in author_folder.iterdir():
            if parse_post_folder_id(path.name) != prefix:
                continue
            canonical = canonical_post_folder(
                self._root,
                path.relative_to(self._root).as_posix(),
                author_folder.name,
                post_id,
            )
            if directory_exists(self._root / canonical) and not _foreign_owner(
                session,
                canonical,
                author_folder.name,
                post_id,
            ):
                candidates.add(canonical)
        return _unique_candidate(candidates)

    def _prepare_row(self, session: Session, folder: str, record: StoredPost) -> DbPost:
        post = record.post
        _require_ownership(session, folder, post.author, post.id)
        row = find_post_row(session, post.author, post.id)
        if row is None:
            return _create_row(session, post)
        current = self._saved_folder(row)
        if current is not None and current != folder:
            message = f'Post {post.author}/{post.id} already occupies {current}'
            raise ValueError(message)
        if row.folder is not None and current is None:
            _reset_generation(session, row)
        return row


def _require_canonical_folder(root: Path, folder: str, post: PostMetadata) -> None:
    if canonical_post_folder(root, folder, post.author, post.id) != folder:
        message = 'Post folder changed its canonical location during save'
        raise ValueError(message)


def _foreign_owner(session: Session, folder: str, author: str, post_id: str) -> bool:
    reservations = session.scalars(
        select(DbPost.folder).where(
            DbPost.author == author,
            DbPost.post_id != post_id,
            DbPost.folder.is_not(None),
        )
    )
    key = portable_path_key(folder)
    return any(
        path is not None and portable_path_key(path) == key for path in reservations
    )


def _require_ownership(
    session: Session, folder: str, author: str, post_id: str
) -> None:
    if _foreign_owner(session, folder, author, post_id):
        message = f'Post folder belongs to another post: {folder}'
        raise ValueError(message)


def _unique_candidate(folders: set[str]) -> LocatedPost | None:
    if len(folders) > 1:
        message = f'Multiple unowned post folders: {", ".join(sorted(folders))}'
        raise AmbiguousPostFolderError(message)
    return LocatedPost(next(iter(folders))) if folders else None


def _create_row(session: Session, post: PostMetadata) -> DbPost:
    ensure_author(session, post.author)
    row = DbPost(author=post.author, post_id=post.id, access=PostAccess.open)
    session.add(row)
    return row


def _reset_generation(session: Session, row: DbPost) -> None:
    session.execute(delete(DbMedia).where(DbMedia.post_row_id == row.id))
    session.execute(delete(DbMarks).where(DbMarks.post_row_id == row.id))
    session.execute(delete(DbMediaMarks).where(DbMediaMarks.post_row_id == row.id))


def _update_inventory(session: Session, row: DbPost, record: StoredPost) -> None:
    existing = {
        entry.media_id: entry
        for entry in session.scalars(
            select(DbMedia).where(DbMedia.post_row_id == row.id),
        )
    }
    for media_id, entry in record.media.items():
        current = existing.pop(media_id, None)
        if current is None:
            current = DbMedia(post_row_id=row.id, author=row.author, media_id=media_id)
            session.add(current)
        update_media_entry(current, entry)
    for obsolete in existing.values():
        session.delete(obsolete)
