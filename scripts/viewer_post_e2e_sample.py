"""Build an isolated canonical post-reading corpus with playable fallback media."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from library_sample.asset_models import AssetBackend, AssetCatalog
from library_sample.assets import create_assets

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    Block,
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
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

AUTHOR = 'reader_checks'
SHORTCUT_AUTHOR = 'shortcut_checks'
MONTH_AUTHOR = 'month_checks'
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
Fragment = PostDataChunkText.TextFragment


@dataclass(frozen=True, slots=True)
class Scenario:
    """One independent page and its initial access and playback state."""

    number: int
    title: str
    tags: tuple[str, ...]
    saved: bool = True
    locked: bool = False
    position: float = 0
    finished: bool = False
    tied: bool = False
    security: bool = False

    @property
    def post_id(self) -> str:
        return f'00000000-0000-4000-8000-{self.number:012d}'


@dataclass(frozen=True, slots=True)
class FixtureMedia:
    """Canonical entries and immutable file sources keyed by media identity."""

    entries: dict[str, MediaEntry]
    sources: dict[str, Path]


@dataclass(frozen=True, slots=True)
class MonthScenario:
    """One populated UTC month in a sparse seven-year history."""

    year: int
    month: int
    milestone: bool = False


MONTHS = (
    MonthScenario(2019, 1, milestone=True),
    MonthScenario(2019, 9),
    MonthScenario(2020, 2),
    MonthScenario(2020, 11, milestone=True),
    MonthScenario(2021, 3, milestone=True),
    MonthScenario(2021, 5),
    MonthScenario(2021, 12),
    MonthScenario(2022, 6, milestone=True),
    MonthScenario(2023, 1),
    MonthScenario(2023, 10),
    MonthScenario(2024, 2, milestone=True),
    MonthScenario(2024, 7),
    MonthScenario(2025, 4),
    MonthScenario(2025, 12, milestone=True),
    MonthScenario(2026, 1),
    MonthScenario(2026, 10, milestone=True),
)


SCENARIOS = (
    Scenario(1, 'Earlier tied post', ('pager', 'pair'), tied=True),
    Scenario(2, 'Complete saved post', ('pager', 'reading'), tied=True),
    Scenario(3, 'Later tied post', ('pager', 'pair'), tied=True),
    Scenario(10, 'Favorite persistence', ('favorite',)),
    Scenario(11, 'Playback persistence', ('playback',), position=7),
    Scenario(12, 'Retained locked post', ('locked',), locked=True, position=5),
    Scenario(13, 'Never saved locked post', ('locked',), saved=False, locked=True),
    Scenario(14, 'Finished playback', ('finished',), finished=True),
    Scenario(15, 'Playback boundary', ('boundary',)),
    Scenario(
        16,
        '<img src=x onerror="window.__postAttack=1">',
        ('<svg onload="window.__postAttack=2">',),
        security=True,
    ),
)


def _metadata(scenario: Scenario) -> PostMetadata:
    created = NOW if scenario.tied else NOW - timedelta(days=scenario.number)
    return PostMetadata(
        scenario.post_id,
        AUTHOR,
        f'https://boosty.to/{AUTHOR}/posts/{scenario.post_id}',
        scenario.title,
        created,
        created,
        tags=list(scenario.tags),
        tier='Studio',
        tier_price_rub=300,
        post_price_rub=500,
        content_counters={'ok_video': 1, 'image': 2},
    )


def _blocks(scenario: Scenario) -> list[Block]:
    blocks: list[Block] = [
        TextBlock([Fragment('A complete reading page', header_level=2)]),
        ParagraphBreak(),
        TextBlock(
            [
                Fragment('Needle café ёлка йога ива. '),
                Fragment('A second needle finishes the paragraph.'),
            ]
        ),
        ParagraphBreak(),
        TextBlock(
            [
                Fragment(
                    'Another saved post',
                    f'https://boosty.to/{AUTHOR}/posts/{SCENARIOS[0].post_id}?tag=pair#chapter',
                )
            ]
        ),
        ParagraphBreak(),
        TextBlock([Fragment('External reference', 'https://example.org/reference')]),
        ParagraphBreak(),
        *[
            MediaBlock(key)
            for key in (
                'image:first',
                'audio:track',
                'image:second',
                'boosty_video:movie',
                'file:notes',
                'file:missing',
            )
        ],
    ]
    if scenario.security:
        blocks.extend(
            [
                ParagraphBreak(),
                TextBlock([Fragment('<script>window.__postAttack=3</script>')]),
                ParagraphBreak(),
                TextBlock(
                    [Fragment('Unsafe destination', 'javascript:window.__postAttack=4')]
                ),
            ]
        )
    return blocks


def _piece(
    kind: MediaKind, position: int, path: str, source: Path, *, removed: bool = False
) -> MediaEntry:
    return MediaEntry(
        kind,
        MediaStatus.downloaded,
        NOW,
        position,
        removed_at=NOW + timedelta(days=1) if removed else None,
        path=path,
        size=source.stat().st_size,
        title=Path(path).stem,
    )


def _media(assets: AssetCatalog) -> FixtureMedia:
    files = {
        'image:first': assets.images[0].path,
        'image:second': assets.images[1].path,
        'audio:track': assets.audio[0].path,
        'boosty_video:movie': assets.videos[0].path,
        'file:notes': assets.attachments[0].path,
        'image:retained': assets.images[2].path,
        'file:retained': assets.attachments[0].path,
    }
    media = {
        key: _piece(
            MediaKind(key.split(':')[0]),
            index,
            f'media/{index}-{source.name}',
            source,
            removed=key.endswith(':retained'),
        )
        for index, (key, source) in enumerate(files.items())
    }
    media['audio:track'].path = "media/Голос !'() # 100%25.wav"
    media['audio:track'].duration = assets.audio[0].duration
    media['boosty_video:movie'].path = "media/Видео !'() # 100%25.mp4"
    media['boosty_video:movie'].duration = assets.videos[0].duration
    media['file:retained'].title = 'Retained glossary'
    media['file:retained'].filename = 'Retained glossary.pdf'
    media['file:missing'] = MediaEntry(
        MediaKind.file,
        MediaStatus.pending,
        NOW,
        7,
        path='media/missing.txt',
        title='Missing attachment',
    )
    return FixtureMedia(media, files)


def _save(
    root: Path,
    store: JsonPostStore,
    marks: JsonPostMarks,
    scenario: Scenario,
    assets: AssetCatalog,
) -> None:
    metadata = _metadata(scenario)
    if scenario.locked:
        store.save_locked_post(LockedPost(metadata, NOW))
    if not scenario.saved:
        return
    inventory = _media(assets)
    media = inventory.entries
    if scenario.security:
        media['file:notes'].title = '<img src=x onerror="window.__postAttack=5">'
        media['file:notes'].filename = '<img src=x onerror="window.__postAttack=5">'
    record = StoredPost(metadata, PostSync(NOW, NOW), _blocks(scenario), media)
    folder = store.choose_post_folder(metadata)
    store.save_post(folder, record)
    for key, source in inventory.sources.items():
        destination = root / folder / str(media[key].path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, destination)
    position = PlaybackPosition(scenario.position, NOW if scenario.finished else None)
    marks.save_marks(
        AUTHOR,
        scenario.post_id,
        PostMarks(positions={'audio:track': position, 'boosty_video:movie': position}),
    )


def _shortcut_metadata(number: int) -> PostMetadata:
    post_id = f'10000000-0000-4000-8000-{number:012d}'
    created = NOW - timedelta(days=number)
    parity = 'even' if number % 2 == 0 else 'odd'
    return PostMetadata(
        post_id,
        SHORTCUT_AUTHOR,
        f'https://boosty.to/{SHORTCUT_AUTHOR}/posts/{post_id}',
        f'Shortcut post {number:02d}',
        created,
        created,
        tags=['keyboard', parity],
    )


def _save_shortcut(store: JsonPostStore, marks: JsonPostMarks, number: int) -> None:
    metadata = _shortcut_metadata(number)
    record = StoredPost(
        metadata,
        PostSync(NOW, NOW),
        [TextBlock([Fragment('Shortcut café reading sequence.')])],
    )
    store.save_post(store.choose_post_folder(metadata), record)
    marks.save_marks(SHORTCUT_AUTHOR, metadata.id, PostMarks(favorite=True))


def _month_metadata(scenario: MonthScenario, day: int) -> PostMetadata:
    number = scenario.year * 10_000 + scenario.month * 100 + day
    post_id = f'20000000-0000-4000-8000-{number:012d}'
    created = datetime(scenario.year, scenario.month, day, tzinfo=timezone.utc)
    tags = [
        'archive',
        'milestone' if scenario.milestone else 'ordinary',
        f'month-{created:%Y-%m}',
    ]
    return PostMetadata(
        post_id,
        MONTH_AUTHOR,
        f'https://boosty.to/{MONTH_AUTHOR}/posts/{post_id}',
        f'Archive {created:%Y-%m-%d}',
        created,
        created,
        tags=tags,
    )


def _save_month(
    store: JsonPostStore, marks: JsonPostMarks, scenario: MonthScenario
) -> None:
    for day in (3, 12, 24):
        metadata = _month_metadata(scenario, day)
        blocks: list[Block] = []
        for paragraph in range(24):
            blocks.extend(
                [
                    TextBlock(
                        [Fragment(f'Archive reading paragraph {paragraph + 1}.')]
                    ),
                    ParagraphBreak(),
                ]
            )
        record = StoredPost(metadata, PostSync(NOW, NOW), blocks)
        store.save_post(store.choose_post_folder(metadata), record)
        marks.save_marks(MONTH_AUTHOR, metadata.id, PostMarks(favorite=True))


def prepare(root: Path) -> None:
    """Populate only a fresh temporary library owned by one browser-test worker."""
    root.mkdir()
    initialize_library(root)
    assets = create_assets(
        root / '.boosty-downloader' / 'reader-assets',
        seed=7,
        backend=AssetBackend.fallback,
    )
    store, marks = JsonPostStore(root), JsonPostMarks(root)
    store.save_author(AuthorInfo(AUTHOR, NOW, title='Post Reader Checks'))
    for scenario in SCENARIOS:
        _save(root, store, marks, scenario, assets)
    store.save_author(AuthorInfo(SHORTCUT_AUTHOR, NOW, title='Shortcut Checks'))
    for number in range(1, 13):
        _save_shortcut(store, marks, number)
    store.save_author(AuthorInfo(MONTH_AUTHOR, NOW, title='Month Checks'))
    for scenario in MONTHS:
        _save_month(store, marks, scenario)
    LibraryIndex(root).rebuild()


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
