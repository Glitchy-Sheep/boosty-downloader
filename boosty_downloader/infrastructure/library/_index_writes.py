"""Transactional projection writes, including synchronized tags, media and FTS."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias, cast

from sqlalchemy import bindparam, delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert

from boosty_downloader.domain.library import PostAccess, PostIdentity
from boosty_downloader.infrastructure.library._index_models import (
    IndexAuthor,
    IndexMedia,
    IndexPost,
    IndexPostTag,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy import Connection

    from boosty_downloader.infrastructure.library.index_projection import (
        AuthorProjection,
        MediaProjection,
        PostProjection,
    )
    from boosty_downloader.infrastructure.library.index_sources import SourceFingerprint

SqlValues: TypeAlias = dict[str, object]


def write_author(
    connection: Connection, author: AuthorProjection, *, locked_synced: bool = True
) -> None:
    """Refresh source metadata without resetting derived post counts."""
    info = author.info
    values: SqlValues = {
        'author': author.author,
        'locked_json_synced': locked_synced,
        'title': info.title if info else None,
        'owner_name': info.owner_name if info else None,
        'description': info.description if info else None,
        'avatar_path': info.avatar_path if info else None,
        'cover_path': info.cover_path if info else None,
        'synced_at': info.synced_at if info else None,
        'remote_post_count': info.remote_post_count if info else None,
        **_fingerprint_values('author_json', author.author_fingerprint),
        **_fingerprint_values('locked_json', author.locked_fingerprint),
    }
    statement = insert(IndexAuthor).values(**values)
    connection.execute(
        statement.on_conflict_do_update(index_elements=['author'], set_=values)
    )


def write_posts(connection: Connection, posts: Sequence[PostProjection]) -> None:
    """Replace each complete post projection and all of its secondary rows."""
    if not posts:
        return
    authors = sorted({post.metadata.author for post in posts})
    connection.execute(
        insert(IndexAuthor).on_conflict_do_nothing(),
        [{'author': author} for author in authors],
    )
    values = [_post_values(post) for post in posts]
    statement = insert(IndexPost)
    statement = statement.on_conflict_do_update(
        index_elements=['author', 'post_id'],
        set_={name: statement.excluded[name] for name in values[0]},
    )
    rows = connection.execute(
        statement.returning(IndexPost.id, IndexPost.author, IndexPost.post_id), values
    ).mappings()
    identifiers = {
        PostIdentity(cast('str', row['author']), cast('str', row['post_id'])): cast(
            'int', row['id']
        )
        for row in rows
    }
    _clear_post_children(connection, tuple(identifiers.values()))
    _write_post_children(connection, identifiers, posts)


def _post_values(post: PostProjection) -> SqlValues:
    metadata = post.metadata
    return {
        'author': metadata.author,
        'post_id': metadata.id,
        'folder': post.folder,
        'url': metadata.url,
        'title': metadata.title,
        'created_at': metadata.created_at,
        'updated_at': metadata.updated_at,
        'published_at': metadata.published_at,
        'access': post.access.value,
        'origin': post.origin,
        'tier': metadata.tier,
        'tier_price_rub': metadata.tier_price_rub,
        'post_price_rub': metadata.post_price_rub,
        'likes': metadata.likes,
        'comments': metadata.comments,
        'tags': list(metadata.tags),
        'content_counters': metadata.content_counters,
        'current_counts': {
            kind.value: count for kind, count in post.current_counts.items()
        },
        'downloaded_counts': {
            kind.value: count for kind, count in post.downloaded_counts.items()
        },
        'cover_path': post.cover_path,
        'teaser_path': post.teaser_path,
        'excerpt': post.excerpt,
        'pieces_added_at': post.pieces_added_at,
        'seen_at': post.marks.seen_at,
        'favorite': post.marks.favorite,
        **_fingerprint_values('post_json', post.record_fingerprint),
        **_fingerprint_values('viewer_json', post.marks_fingerprint),
    }


def _fingerprint_values(
    prefix: str, fingerprint: SourceFingerprint | None
) -> SqlValues:
    return {
        f'{prefix}_mtime_ns': fingerprint.mtime_ns if fingerprint else None,
        f'{prefix}_size': fingerprint.size if fingerprint else None,
    }


def _clear_post_children(connection: Connection, identifiers: Sequence[int]) -> None:
    connection.execute(
        delete(IndexPostTag).where(IndexPostTag.post_row_id.in_(identifiers))
    )
    connection.execute(
        delete(IndexMedia).where(IndexMedia.post_row_id.in_(identifiers))
    )
    statement = text('DELETE FROM posts_fts WHERE rowid IN :identifiers').bindparams(
        bindparam('identifiers', expanding=True)
    )
    connection.execute(statement, {'identifiers': identifiers})


@dataclass(frozen=True, slots=True)
class _PostChildren:
    tags: list[SqlValues] = field(default_factory=list[SqlValues])
    media: list[SqlValues] = field(default_factory=list[SqlValues])
    search: list[SqlValues] = field(default_factory=list[SqlValues])


def _collect_post_children(
    identifiers: Mapping[PostIdentity, int], posts: Sequence[PostProjection]
) -> _PostChildren:
    rows = _PostChildren()
    for post in posts:
        row_id = identifiers[PostIdentity(post.metadata.author, post.metadata.id)]
        rows.tags.extend(
            {'post_row_id': row_id, 'tag': tag}
            for tag in dict.fromkeys(post.metadata.tags)
        )
        rows.media.extend(_media_values(row_id, post, media) for media in post.media)
        rows.search.append(_search_values(row_id, post))
    return rows


def _write_post_children(
    connection: Connection,
    identifiers: Mapping[PostIdentity, int],
    posts: Sequence[PostProjection],
) -> None:
    rows = _collect_post_children(identifiers, posts)
    if rows.tags:
        connection.execute(insert(IndexPostTag), rows.tags)
    if rows.media:
        connection.execute(insert(IndexMedia), rows.media)
    connection.execute(
        text(
            'INSERT INTO posts_fts(rowid, title, body, original_title, original_body) VALUES (:rowid, :title, :body, :original_title, :original_body)'
        ),
        rows.search,
    )


def _search_values(row_id: int, post: PostProjection) -> SqlValues:
    return {
        'rowid': row_id,
        'title': post.title_folded,
        'body': post.text_folded,
        'original_title': post.title,
        'original_body': post.text,
    }


def _media_values(
    row_id: int, post: PostProjection, media: MediaProjection
) -> SqlValues:
    entry, playback = media.entry, media.playback
    return {
        'post_row_id': row_id,
        'author': post.metadata.author,
        'post_id': post.metadata.id,
        'media_id': media.media_id,
        'kind': entry.kind.value,
        'status': entry.status.value,
        'position': media.position,
        'path': _library_path(post.folder, entry.path),
        'thumbnail_path': media.thumbnail_path,
        'preview_path': _library_path(post.folder, entry.preview_path),
        'title': entry.title,
        'filename': entry.filename,
        'artist': entry.artist,
        'size': entry.size,
        'duration': entry.duration.total_seconds()
        if entry.duration is not None
        else None,
        'width': entry.width,
        'height': entry.height,
        'added_at': entry.added_at,
        'removed_at': entry.removed_at,
        'playback_position': playback.seconds if playback else None,
        'finished_at': playback.finished_at if playback else None,
    }


def _library_path(folder: str | None, path: str | None) -> str | None:
    if path is None:
        return None
    if folder is None:
        message = 'Indexed local media requires a saved post folder'
        raise ValueError(message)
    return f'{folder}/{path}'


def refresh_author_counts(connection: Connection, *, author: str | None = None) -> None:
    """Count current post access for one author, or the whole rebuilt index."""
    posts = (
        select(func.count())
        .where(IndexPost.author == IndexAuthor.author)
        .scalar_subquery()
    )
    locked = (
        select(func.count())
        .where(
            IndexPost.author == IndexAuthor.author,
            IndexPost.access == PostAccess.locked.value,
        )
        .scalar_subquery()
    )
    statement = update(IndexAuthor).values(post_count=posts, locked_post_count=locked)
    if author is not None:
        statement = statement.where(IndexAuthor.author == author)
    connection.execute(statement)


def delete_post(connection: Connection, author: str, post_id: str) -> None:
    """Remove a vanished post from every index projection."""
    row_id = connection.scalar(
        select(IndexPost.id).where(
            IndexPost.author == author, IndexPost.post_id == post_id
        )
    )
    if row_id is not None:
        _clear_post_children(connection, (row_id,))
        connection.execute(delete(IndexPost).where(IndexPost.id == row_id))


def delete_posts(connection: Connection, identifiers: Sequence[int]) -> None:
    """Remove known post rows and their FTS entries in bounded batches."""
    batch_size = 200
    for offset in range(0, len(identifiers), batch_size):
        batch = identifiers[offset : offset + batch_size]
        _clear_post_children(connection, batch)
        connection.execute(delete(IndexPost).where(IndexPost.id.in_(batch)))
