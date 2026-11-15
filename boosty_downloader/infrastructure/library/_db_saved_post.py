"""Confirm saved folder ownership and content within the caller's database snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.infrastructure.library._db_models import DbMedia, DbPost
from boosty_downloader.infrastructure.library._db_post_mapping import read_saved_post
from boosty_downloader.infrastructure.library._db_post_paths import (
    canonical_post_folder,
    directory_exists,
    portable_path_key,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session


def saved_post_folder(root: Path, row: DbPost) -> str | None:
    """Hide missing generations and reject a redirected canonical post location."""
    if row.folder is None:
        return None
    canonical = canonical_post_folder(root, row.folder, row.author, row.post_id)
    if canonical != row.folder:
        message = f'Saved post folder redirects its canonical location: {row.folder}'
        raise ValueError(message)
    if not directory_exists(root / canonical):
        return None
    return canonical


def read_saved_location(
    session: Session, root: Path, row: DbPost
) -> LocatedPost | None:
    """Read a complete confirmed generation without opening a separate transaction."""
    folder = saved_post_folder(root, row)
    if folder is None:
        return None
    require_folder_ownership(session, folder, row.author, row.post_id)
    media = list(
        session.scalars(
            select(DbMedia)
            .where(DbMedia.post_row_id == row.id)
            .order_by(DbMedia.position, DbMedia.media_id)
        )
    )
    return LocatedPost(folder, read_saved_post(row, media))


def has_foreign_folder_owner(
    session: Session, folder: str, author: str, post_id: str
) -> bool:
    """Keep portable folder reservations exclusive across full post identities."""
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


def require_folder_ownership(
    session: Session, folder: str, author: str, post_id: str
) -> None:
    """Reject a folder reserved by another full post identity."""
    if has_foreign_folder_owner(session, folder, author, post_id):
        message = f'Post folder belongs to another post: {folder}'
        raise ValueError(message)
