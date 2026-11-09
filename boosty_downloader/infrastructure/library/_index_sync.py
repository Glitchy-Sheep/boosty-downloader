"""Atomic incremental synchronization of canonical sources and their index."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from sqlalchemy import delete, select

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.infrastructure.library._index_inventory import (
    AuthorInventory,
    PostInventory,
    inventory_sources,
)
from boosty_downloader.infrastructure.library._index_models import (
    IndexAuthor,
    IndexPost,
)
from boosty_downloader.infrastructure.library._index_writes import (
    delete_posts,
    refresh_author_counts,
    write_author,
    write_posts,
)
from boosty_downloader.infrastructure.library.errors import AmbiguousPostFolderError
from boosty_downloader.infrastructure.library.index_projection import (
    AuthorProjection,
    PostProjection,
    project_author,
    project_post,
)
from boosty_downloader.infrastructure.library.index_sources import (
    AuthorSource,
    SourceFingerprint,
    locked_post_source,
    read_author_source,
    read_post_source_with_observations,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy import Connection, RowMapping


@dataclass(frozen=True, slots=True)
class IndexSyncCounts:
    """
    Committed metadata refreshes, post upserts and removals since preparation.

    Author updates exclude derived post-count refreshes. A complete rebuild
    reports only rebuilt=True; its rows are not incremental changes.
    """

    rebuilt: bool = False
    authors_updated: int = 0
    posts_updated: int = 0
    posts_removed: int = 0
    authors_removed: int = 0


@dataclass(frozen=True, slots=True)
class _IndexedAuthorSources:
    info: SourceFingerprint | None
    locked: SourceFingerprint | None
    locked_synced: bool


@dataclass(frozen=True, slots=True)
class _IndexedPostSources:
    row_id: int
    post_id: str
    folder: str | None
    access: PostAccess
    record: SourceFingerprint | None
    marks: SourceFingerprint | None


@dataclass(slots=True)
class _AuthorChanges:
    metadata: AuthorProjection | None = None
    posts: list[PostProjection] = field(default_factory=list[PostProjection])
    removed: list[int] = field(default_factory=list[int])


def synchronize(connection: Connection, root: Path) -> IndexSyncCounts:
    """Commit all changed projections together, leaving canonical files untouched."""
    authors = _read_authors(connection)
    posts = _read_posts(connection)
    inventory = inventory_sources(root)
    authors_updated = posts_updated = posts_removed = 0
    for author, sources in inventory.items():
        changes = _author_changes(
            root, sources, authors.get(author), posts.get(author, {})
        )
        _apply_changes(connection, author, changes)
        authors_updated += int(changes.metadata is not None)
        posts_updated += len(changes.posts)
        posts_removed += len(changes.removed)
    vanished = authors.keys() - inventory.keys()
    removed = [
        post.row_id for author in vanished for post in posts.get(author, {}).values()
    ]
    delete_posts(connection, removed)
    for author in vanished:
        connection.execute(delete(IndexAuthor).where(IndexAuthor.author == author))
    return IndexSyncCounts(
        authors_updated=authors_updated,
        posts_updated=posts_updated,
        posts_removed=posts_removed + len(removed),
        authors_removed=len(vanished),
    )


def _read_authors(connection: Connection) -> dict[str, _IndexedAuthorSources]:
    rows = connection.execute(
        select(
            IndexAuthor.author,
            IndexAuthor.author_json_mtime_ns,
            IndexAuthor.author_json_size,
            IndexAuthor.locked_json_mtime_ns,
            IndexAuthor.locked_json_size,
            IndexAuthor.locked_json_synced,
        )
    ).mappings()
    return {
        cast('str', row['author']): _IndexedAuthorSources(
            _fingerprint(row, 'author_json'),
            _fingerprint(row, 'locked_json'),
            cast('bool', row['locked_json_synced']),
        )
        for row in rows
    }


def _read_posts(connection: Connection) -> dict[str, dict[str, _IndexedPostSources]]:
    rows = connection.execute(
        select(
            IndexPost.id,
            IndexPost.author,
            IndexPost.post_id,
            IndexPost.folder,
            IndexPost.access,
            IndexPost.post_json_mtime_ns,
            IndexPost.post_json_size,
            IndexPost.viewer_json_mtime_ns,
            IndexPost.viewer_json_size,
        )
    ).mappings()
    posts: dict[str, dict[str, _IndexedPostSources]] = {}
    for row in rows:
        post_id = cast('str', row['post_id'])
        posts.setdefault(cast('str', row['author']), {})[post_id] = _IndexedPostSources(
            cast('int', row['id']),
            post_id,
            cast('str | None', row['folder']),
            PostAccess(row['access']),
            _fingerprint(row, 'post_json'),
            _fingerprint(row, 'viewer_json'),
        )
    return posts


def _fingerprint(row: RowMapping, prefix: str) -> SourceFingerprint | None:
    modified = cast('int | None', row[f'{prefix}_mtime_ns'])
    size = cast('int | None', row[f'{prefix}_size'])
    return (
        SourceFingerprint(modified, size)
        if modified is not None and size is not None
        else None
    )


def _author_changes(
    root: Path,
    inventory: AuthorInventory,
    previous: _IndexedAuthorSources | None,
    posts: dict[str, _IndexedPostSources],
) -> _AuthorChanges:
    folders = {post.folder: post for post in posts.values() if post.folder is not None}
    if not _needs_author_read(inventory, previous, folders):
        return _AuthorChanges()
    source = read_author_source(root, inventory.author)
    access_changed = _access_changed(source, previous)
    changes = _AuthorChanges()
    if _metadata_changed(source, previous) or access_changed:
        changes.metadata = project_author(source)
    seen: set[str] = set()
    for folder, current in inventory.posts.items():
        cached = folders.get(folder)
        if _post_changed(current, cached) or _needs_access_refresh(
            source, cached, access_changed=access_changed
        ):
            _read_changed_post(root, current, source, seen, changes)
        elif cached is not None:
            _remember_identity(source.author, cached.post_id, seen)
    changes.posts.extend(
        _locked_without_body(root, source, posts, seen, access_changed=access_changed)
    )
    changes.removed = [
        post.row_id for post_id, post in posts.items() if post_id not in seen
    ]
    return changes


def _needs_author_read(
    current: AuthorInventory,
    previous: _IndexedAuthorSources | None,
    folders: dict[str, _IndexedPostSources],
) -> bool:
    if previous is None or not previous.locked_synced:
        return True
    if current.info != previous.info or current.locked != previous.locked:
        return True
    if current.posts.keys() != folders.keys():
        return True
    return any(
        _post_changed(post, folders.get(folder))
        for folder, post in current.posts.items()
    )


def _post_changed(current: PostInventory, previous: _IndexedPostSources | None) -> bool:
    return (
        previous is None
        or current.record != previous.record
        or current.marks != previous.marks
    )


def _access_changed(
    source: AuthorSource, previous: _IndexedAuthorSources | None
) -> bool:
    return (
        previous is None
        or not previous.locked_synced
        or source.locked_fingerprint != previous.locked
    )


def _metadata_changed(
    source: AuthorSource, previous: _IndexedAuthorSources | None
) -> bool:
    return previous is None or source.author_fingerprint != previous.info


def _needs_access_refresh(
    source: AuthorSource, cached: _IndexedPostSources | None, *, access_changed: bool
) -> bool:
    return (
        access_changed
        and cached is not None
        and (
            cached.access is PostAccess.locked or cached.post_id in source.locked_posts
        )
    )


def _read_changed_post(
    root: Path,
    inventory: PostInventory,
    author: AuthorSource,
    seen: set[str],
    changes: _AuthorChanges,
) -> None:
    source = read_post_source_with_observations(
        root, inventory.folder, author.locked_posts
    )
    if source is not None:
        _remember_identity(author.author, source.post.overview.post.id, seen)
        changes.posts.append(project_post(source))


def _remember_identity(author: str, post_id: str, seen: set[str]) -> None:
    if post_id in seen:
        message = f'Multiple post folders for {author}/{post_id}'
        raise AmbiguousPostFolderError(message)
    seen.add(post_id)


def _locked_without_body(
    root: Path,
    author: AuthorSource,
    previous: dict[str, _IndexedPostSources],
    seen: set[str],
    *,
    access_changed: bool,
) -> list[PostProjection]:
    projections: list[PostProjection] = []
    for post_id, locked in author.locked_posts.items():
        if post_id in seen:
            continue
        seen.add(post_id)
        cached = previous.get(post_id)
        if access_changed or cached is None or cached.folder is not None:
            projections.append(project_post(locked_post_source(root, locked)))
    return projections


def _apply_changes(
    connection: Connection, author: str, changes: _AuthorChanges
) -> None:
    if changes.metadata is not None:
        write_author(connection, changes.metadata)
    delete_posts(connection, changes.removed)
    batch_size = 100
    for offset in range(0, len(changes.posts), batch_size):
        write_posts(connection, changes.posts[offset : offset + batch_size])
    if changes.posts or changes.removed:
        refresh_author_counts(connection, author=author)
