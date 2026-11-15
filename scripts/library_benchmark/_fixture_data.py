"""Deterministic canonical records used by the production library benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from boosty_downloader.domain.stored_post import Block

BENCHMARK_TAG: Final = 'tutorial'
SEARCH_TEXT: Final = 'needle'
SEARCH_QUERY: Final = 'need shad'
TAGS: Final = ('art', 'music', 'devlog', 'stream', 'lore', 'beta', 'audio', 'учеба')
_BASE_DATE: Final = datetime(2020, 1, 1, tzinfo=timezone.utc)
_MEDIA_PER_POST: Final = 5
_STATUS_CYCLE: Final = 20
_DOWNLOADED_SLOTS: Final = 16
_REMAINING_STATUSES: Final = (
    MediaStatus.pending,
    MediaStatus.failed,
    MediaStatus.unavailable,
    MediaStatus.deleted,
)
_PARAGRAPH: Final = (
    'Shader tutorial music development art sketch and animation. '
    'Практика рисования, всё о звуке и создании персонажа. '
    'The lesson explains materials, lighting, rhythm and composition. '
)


@dataclass(frozen=True, slots=True)
class FixtureConfig:
    """Stable dimensions and content seed; small dimensions support correctness tests."""

    authors: int = 20
    posts_per_author: int = 1000
    seed: int = 20261109

    def __post_init__(self) -> None:
        if (
            type(self.authors) is not int
            or type(self.posts_per_author) is not int
            or type(self.seed) is not int
            or self.authors < 1
            or self.posts_per_author < 1
            or not 0 <= self.seed < 2**32
        ):
            message = 'Fixture requires positive integer dimensions and a uint32 seed'
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class FixturePost:
    """One generated canonical post, its relative folder and optional user/access data."""

    folder: str
    record: StoredPost
    marks: PostMarks | None
    locked: LockedPost | None


def author_name(index: int) -> str:
    """Return the portable deterministic author name."""
    return f'author{index:03d}'


def iter_fixture_posts(config: FixtureConfig) -> Iterator[FixturePost]:
    """Yield fresh independent domain objects in author/post order."""
    for author_index in range(config.authors):
        for number in range(config.posts_per_author):
            yield _make_post(config, author_index, number)


def _make_post(config: FixtureConfig, author_index: int, number: int) -> FixturePost:
    metadata = _metadata(config, author_index, number)
    media = _media(config, author_index, number, metadata.created_at)
    record = StoredPost(
        metadata,
        PostSync(metadata.created_at, metadata.updated_at),
        _blocks(media, number),
        media,
    )
    folder = compose_post_directory_name(
        metadata.title, metadata.created_at, metadata.id
    )
    locked = LockedPost(metadata, metadata.updated_at) if number % 20 == 0 else None
    return FixturePost(
        f'{metadata.author}/{folder}', record, _marks(record, number), locked
    )


def _metadata(config: FixtureConfig, author_index: int, number: int) -> PostMetadata:
    author = author_name(author_index)
    identity = author_index * config.posts_per_author + number
    post_id = f'{identity:08x}-{config.seed:08x}-benchmark'
    created = _BASE_DATE + timedelta(days=number, hours=author_index % 24)
    title = f'Lesson {number}: shader practice'
    if number % 7 == 0:
        title += ' Needle'
    tags = [TAGS[(number + config.seed) % len(TAGS)]]
    if number % 3 == 0:
        tags.append(BENCHMARK_TAG)
    return PostMetadata(
        post_id,
        author,
        f'https://boosty.to/{author}/posts/{post_id}',
        title,
        created,
        created + timedelta(days=7),
        tags=tags,
        likes=number % 100,
        comments=number % 13,
    )


def _kinds(number: int) -> tuple[MediaKind, ...]:
    video = MediaKind.boosty_video if number % 2 == 0 else MediaKind.external_video
    return (MediaKind.image, MediaKind.image, video, MediaKind.file, MediaKind.audio)


def _status(
    config: FixtureConfig, author_index: int, number: int, position: int
) -> MediaStatus:
    slot = (config.seed + author_index + number + position * 3) % _STATUS_CYCLE
    if slot < _DOWNLOADED_SLOTS:
        return MediaStatus.downloaded
    return _REMAINING_STATUSES[slot - _DOWNLOADED_SLOTS]


def _media(
    config: FixtureConfig, author_index: int, number: int, created: datetime
) -> dict[str, MediaEntry]:
    entries: dict[str, MediaEntry] = {}
    for position, kind in enumerate(_kinds(number)):
        identity = (
            author_index * config.posts_per_author + number
        ) * _MEDIA_PER_POST + position
        removed = created + timedelta(days=6) if identity % 101 == 0 else None
        added = created + timedelta(days=4) if number % 4 == 0 else created
        entries[_media_id(kind, identity)] = MediaEntry(
            kind,
            _status(config, author_index, number, position),
            added,
            position,
            removed_at=removed,
            path=f'media/{kind.value}-{position}.bin',
            size=100_000 + (identity * 17 + config.seed) % 50_000_000,
            title=f'{kind.value} study {number}',
            filename=f'piece-{position}.bin',
            artist='Synthetic artist',
            duration=timedelta(seconds=120 + number % 300),
        )
    return entries


def _media_id(kind: MediaKind, identity: int) -> str:
    if kind is MediaKind.external_video:
        return f'{kind.value}:https://example.test/watch/{identity}'
    return f'{kind.value}:{identity}'


def _blocks(media: dict[str, MediaEntry], number: int) -> list[Block]:
    blocks: list[Block] = []
    for paragraph in range(4):
        text = f'Lesson {number}, paragraph {paragraph}. {_PARAGRAPH * 2}'
        blocks.extend(
            [TextBlock([PostDataChunkText.TextFragment(text)]), ParagraphBreak()]
        )
    blocks.extend(
        MediaBlock(key) for key, entry in media.items() if entry.removed_at is None
    )
    return blocks


def _marks(record: StoredPost, number: int) -> PostMarks | None:
    if number % 2:
        return None
    seen = record.post.created_at + timedelta(days=3)
    positions = {
        key: PlaybackPosition(float(number % 100), seen if number % 6 == 0 else None)
        for key, entry in record.media.items()
        if entry.kind
        in {MediaKind.boosty_video, MediaKind.external_video, MediaKind.audio}
    }
    return PostMarks(seen_at=seen, favorite=number % 10 == 0, positions=positions)
