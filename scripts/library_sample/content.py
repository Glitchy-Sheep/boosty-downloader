"""Deterministic themed records with explicit small-corpus scenario coverage."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cache
from random import Random
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    Block,
    LineBreak,
    ListBlock,
    ListItem,
    LockedPost,
    MediaBlock,
    MediaKind,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from library_sample.media import build_media
from library_sample.models import (
    AssetPlacement,
    AuthorName,
    SampleAuthor,
    SampleConfig,
    SamplePost,
    Scenario,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from library_sample.asset_models import AssetCatalog

MIN_SCENARIO_POSTS = 24
_SYNCED_AT = datetime(2026, 11, 1, tzinfo=timezone.utc)
_BASE_DATE = datetime(2024, 1, 1, tzinfo=timezone.utc)
Fragment = PostDataChunkText.TextFragment


@dataclass(frozen=True, slots=True)
class AuthorTheme:
    """A stable author identity and its approved content direction."""

    name: str
    title: str
    description: str
    weight: int
    topics: tuple[str, ...]
    tags: tuple[str, ...]


AUTHORS = (
    AuthorTheme(
        AuthorName.devlog.value,
        'Pixel Forge',
        'Девлоги инди-игры про кузницу, пиксель-арт и шейдеры',
        1192,
        (
            'новая система освещения',
            'кузница и крафт',
            'шейдер воды',
            'меню инвентаря',
            'оптимизация рендера',
        ),
        ('devlog', 'стрим', 'шейдеры', 'пиксель-арт', 'патч'),
    ),
    AuthorTheme(
        AuthorName.music.value,
        'Sound Garden',
        'Демо треков, разборы сведения и стемы для подписчиков',
        152,
        ('Ночной город', 'Туманное утро', 'Северный ветер', 'Кофе и дождь'),
        ('демо', 'сведение', 'стемы', 'синты', 'эмбиент'),
    ),
    AuthorTheme(
        AuthorName.art.value,
        'Скетчбук Лены',
        'Иллюстрации, процесс работы и уроки рисования',
        62,
        ('лисица в снегу', 'портрет в профиль', 'городской пейзаж', 'драконья чешуя'),
        ('скетч', 'процесс', 'урок', 'портрет', 'пейзаж'),
    ),
)


def author_counts(config: SampleConfig) -> dict[str, int]:
    """Reserve the scenario prefix, then allocate remaining posts by stable weights."""
    counts = dict.fromkeys((theme.name for theme in AUTHORS), 0)
    for ordinal in range(min(config.posts, MIN_SCENARIO_POSTS)):
        counts[AUTHORS[ordinal % len(AUTHORS)].name] += 1
    remaining = max(0, config.posts - MIN_SCENARIO_POSTS)
    cycle = _weighted_cycle()
    full_cycles, remainder = divmod(remaining, len(cycle))
    partial = Counter(cycle[:remainder])
    for theme in AUTHORS:
        counts[theme.name] += full_cycles * theme.weight + partial[theme.name]
    return counts


@cache
def _weighted_cycle() -> tuple[str, ...]:
    """Every longer prefix adds one identity; a full cycle has the exact weights."""
    counts = dict.fromkeys((theme.name for theme in AUTHORS), 0)
    total_weight = sum(theme.weight for theme in AUTHORS)
    cycle: list[str] = []
    for ordinal in range(total_weight):
        chosen = max(
            AUTHORS,
            key=lambda theme: (
                theme.weight * (ordinal + 1) - counts[theme.name] * total_weight
            ),
        )
        counts[chosen.name] += 1
        cycle.append(chosen.name)
    return tuple(cycle)


def post_id(config: SampleConfig, author: str, ordinal: int) -> str:
    """Identity depends only on the seed, author and local ordinal."""
    return str(uuid5(NAMESPACE_URL, f'boosty-sample:{config.seed}:{author}:{ordinal}'))


def _url(config: SampleConfig, author: str, ordinal: int) -> str:
    return f'https://boosty.to/{author}/posts/{post_id(config, author, ordinal)}'


def build_authors(config: SampleConfig, assets: AssetCatalog) -> list[SampleAuthor]:
    """Include author images and locked-only teasers without creating post folders."""
    counts = author_counts(config)
    return [
        _author(theme, index, counts[theme.name], assets)
        for index, theme in enumerate(AUTHORS)
    ]


def _author(
    theme: AuthorTheme, index: int, count: int, assets: AssetCatalog
) -> SampleAuthor:
    avatar, cover = assets.avatars[index], assets.covers[index]
    avatar_path, cover_path = f'avatar{avatar.path.suffix}', f'cover{cover.path.suffix}'
    files = [
        AssetPlacement(avatar_path, avatar.path),
        AssetPlacement(cover_path, cover.path),
    ]
    if count > Scenario.locked_teaser:
        files.append(AssetPlacement('teasers/locked.png', assets.images[index].path))
    info = AuthorInfo(
        theme.name,
        _SYNCED_AT,
        theme.title,
        theme.title,
        theme.description,
        avatar_path,
        cover_path,
        count,
    )
    return SampleAuthor(info, tuple(files))


def iter_posts(config: SampleConfig, assets: AssetCatalog) -> Iterator[SamplePost]:
    """Yield exact identities; the first eight of each author cover the edge cases."""
    counts = author_counts(config)
    for theme in AUTHORS:
        for ordinal in range(counts[theme.name]):
            yield _post(config, assets, theme, ordinal)


def _metadata(config: SampleConfig, theme: AuthorTheme, ordinal: int) -> PostMetadata:
    draw = Random(f'{config.seed}:{theme.name}:{ordinal}:text')  # noqa: S311 - reproducible sample
    created = _BASE_DATE + timedelta(minutes=90 * ordinal)
    return PostMetadata(
        id=post_id(config, theme.name, ordinal),
        author=theme.name,
        url=_url(config, theme.name, ordinal),
        title=f'{theme.title} #{ordinal + 1}: {draw.choice(theme.topics)}',
        created_at=created,
        updated_at=created + timedelta(hours=1),
        published_at=created,
        tags=draw.sample(list(theme.tags), 2),
        tier='Ранний доступ',
        tier_price_rub=300,
        likes=draw.randrange(1, 800),
        comments=draw.randrange(40),
    )


def _post(
    config: SampleConfig, assets: AssetCatalog, theme: AuthorTheme, ordinal: int
) -> SamplePost:
    metadata = _metadata(config, theme, ordinal)
    if ordinal in {Scenario.locked_teaser, Scenario.locked_no_teaser}:
        teaser = 'teasers/locked.png' if ordinal == Scenario.locked_teaser else None
        metadata.content_counters = {'ok_video': 1, 'image': 2}
        return SamplePost(None, LockedPost(metadata, _SYNCED_AT, teaser), None, ())
    inventory = build_media(metadata, ordinal, assets)
    blocks = _text(config, theme.name)
    blocks.extend(
        MediaBlock(key)
        for key, entry in inventory.entries.items()
        if entry.removed_at is None
    )
    record = StoredPost(
        metadata, PostSync(metadata.created_at, _SYNCED_AT), blocks, inventory.entries
    )
    locked = (
        LockedPost(metadata, _SYNCED_AT) if ordinal == Scenario.lost_access else None
    )
    return SamplePost(record, locked, _marks(record, ordinal), inventory.files)


def _text(config: SampleConfig, author: str) -> list[Block]:
    links: list[Fragment | LineBreak] = [
        Fragment('Предыдущий выпуск', _url(config, author, 1)),
        Fragment('Музыка проекта', _url(config, AuthorName.music.value, 0)),
        Fragment('Для подписчиков', _url(config, author, 2)),
        Fragment('Будущий выпуск', _url(config, author, 999999)),
        Fragment('Сайт проекта', 'https://example.org/'),
    ]
    nested = ListItem([TextBlock([Fragment('Детали и примеры')])])
    blocks: list[Block] = [
        TextBlock([Fragment('Как устроен процесс', header_level=2)]),
        ParagraphBreak(),
        TextBlock(
            [
                Fragment(
                    'Сегодня покажу прототип.', style=Fragment.TextStyle(bold=True)
                ),
                LineBreak(),
                Fragment(
                    'Проверяем всё вместе: шейдер, café, мой новый урок.',
                    style=Fragment.TextStyle(italic=True),
                ),
            ]
        ),
        ParagraphBreak(),
        TextBlock(links),
        ParagraphBreak(),
        ListBlock([ListItem([TextBlock([Fragment('Разобрать пример')])], [nested])]),
        ListBlock(
            [ListItem([TextBlock([Fragment('Сохранить результат')])])],
            PostDataChunkTextualList.ListStyle.ordered,
        ),
    ]

    return blocks


def _marks(record: StoredPost, ordinal: int) -> PostMarks:
    seen = record.post.created_at + timedelta(days=1) if ordinal % 2 else None
    positions: dict[str, PlaybackPosition] = {}
    for index, (media_id, entry) in enumerate(record.media.items()):
        if entry.kind not in {
            MediaKind.audio,
            MediaKind.boosty_video,
            MediaKind.external_video,
        }:
            continue
        seconds = entry.duration.total_seconds() if entry.duration else 24
        match index % 3:
            case 0:
                positions[media_id] = PlaybackPosition()
            case 1:
                positions[media_id] = PlaybackPosition(seconds / 3)
            case _:
                positions[media_id] = PlaybackPosition(
                    0, record.post.created_at + timedelta(hours=2)
                )
    return PostMarks(seen, ordinal % 3 == 0, positions)
