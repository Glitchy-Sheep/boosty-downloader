"""Dry-run predicts final local links without changing saved library files."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from support.memory_post_store import MemoryPostStore

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_plan import build_download_plan
from boosty_downloader.application.post_locations import ReservedPostLocator
from boosty_downloader.application.post_pages import prepare_post_page, render_post_page
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.library import SavedPost
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.page_links import SavedPageLinkResolver
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.download_plan import DownloadPlan

_NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)
_AUTHOR = 'writer'
_FILTERS = [DownloadContentTypeFilter.post_content]


@dataclass(frozen=True, slots=True)
class _FileState:
    content: bytes | None
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _FixedTarget:
    post_id: str
    folder: str

    def post_folder(self, author: str, post_id: str) -> str | None:
        if author == _AUTHOR and post_id == self.post_id:
            return self.folder
        return None


@pytest.fixture
def preparer(tmp_path: Path) -> PostPreparer:
    root = tmp_path / 'library'
    return PostPreparer(root, JsonPostStore(root), _AUTHOR, BoostyOkVideoType.medium)


def _post(post_id: str, *, target: str | None = None, title: str = 'A post') -> PostDTO:
    data: list[dict[str, object]] = []
    if target is not None:
        data.append(
            {
                'type': 'link',
                'url': f'https://boosty.to/{_AUTHOR}/posts/{target}?view=full#part',
                'content': json.dumps(['Next lesson', 'unstyled', []]),
                'explicit': True,
            }
        )
    return PostDTO.model_validate(
        {
            'id': post_id,
            'title': title,
            'createdAt': _NOW,
            'updatedAt': _NOW,
            'hasAccess': True,
            'signedQuery': '',
            'data': data,
        }
    )


def _save(preparer: PostPreparer, post: PostDTO) -> SavedPost:
    prepared = preparer.prepare(post, _FILTERS, _NOW)
    record = prepared.reconciliation.record
    assert record is not None
    assert isinstance(preparer.store, JsonPostStore)
    record.sync.page_template = PAGE_TEMPLATE_VERSION
    preparer.store.save_post(prepared.folder, record)
    render_post_page(
        record,
        root=preparer.library_root,
        folder=prepared.folder,
        link_resolver=SavedPageLinkResolver(
            preparer.library_root, preparer.store.find_post
        ),
    )
    return SavedPost(prepared.folder, record)


def _plan(
    preparer: PostPreparer,
    posts: list[PostDTO],
    *,
    excluded_tags: tuple[str, ...] = (),
) -> DownloadPlan:
    return build_download_plan(
        posts,
        preparer=preparer,
        filters=_FILTERS,
        now=_NOW,
        excluded_tags=excluded_tags,
    )


def _snapshot(root: Path) -> dict[Path, _FileState]:
    return {
        path: _FileState(
            path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
        )
        for path in [root, *root.rglob('*')]
    }


@pytest.mark.parametrize('target_first', [False, True])
def test_a_new_target_changes_its_cached_source_in_either_listing_order(
    preparer: PostPreparer, *, target_first: bool
) -> None:
    source, target = _post('source', target='target'), _post('target')
    _save(preparer, source)
    before = _snapshot(preparer.library_root)
    posts = [target, source] if target_first else [source, target]

    plan = _plan(preparer, posts)

    assert plan.new_posts == 1
    assert plan.updated_posts == 1
    assert plan.unchanged_posts == 0
    assert plan.known_bytes == 0
    assert plan.media == MediaCounts()
    assert _snapshot(preparer.library_root) == before


@pytest.mark.parametrize('target_first', [False, True])
def test_a_restored_target_keeps_an_already_local_source_unchanged(
    preparer: PostPreparer, *, target_first: bool
) -> None:
    source, target = _post('source', target='target'), _post('target')
    saved_target = _save(preparer, target)
    saved_source = _save(preparer, source)
    (preparer.library_root / saved_target.folder / 'post.html').unlink()
    before = _snapshot(preparer.library_root)
    posts = [target, source] if target_first else [source, target]

    plan = _plan(preparer, posts)

    assert plan.new_posts == 0
    assert plan.updated_posts == 1
    assert plan.unchanged_posts == 1
    assert _snapshot(preparer.library_root) == before
    _save(preparer, target)
    _save(preparer, source)
    page = preparer.library_root / saved_source.folder / 'post.html'
    assert _snapshot(preparer.library_root)[page] == before[page]
    assert _plan(preparer, posts).unchanged_posts == 2


@pytest.mark.parametrize('reason', ['absent', 'locked', 'excluded'])
def test_an_unselected_target_is_not_a_prospective_local_page(
    preparer: PostPreparer, reason: str
) -> None:
    source = _post('source', target='target')
    _save(preparer, source)
    posts = [source]
    match reason:
        case 'locked':
            posts.append(_post('target').model_copy(update={'has_access': False}))
        case 'excluded':
            target = _post('target').model_dump()
            target['tags'] = [{'id': 1, 'title': 'skip'}]
            posts.append(PostDTO.model_validate(target))
    before = _snapshot(preparer.library_root)

    plan = _plan(preparer, posts, excluded_tags=('skip',))

    assert plan.unchanged_posts == 1
    assert plan.updated_posts == 0
    assert plan.new_posts == 0
    assert _snapshot(preparer.library_root) == before


def test_a_retained_page_can_resolve_a_locked_target(preparer: PostPreparer) -> None:
    source, target = _post('source', target='target'), _post('target')
    _save(preparer, source)
    _save(preparer, target)

    plan = _plan(preparer, [source, target.model_copy(update={'has_access': False})])

    assert plan.updated_posts == 1
    assert plan.new_posts == 0


@pytest.mark.parametrize('recordless', [False, True])
def test_prospective_collisions_match_the_folders_created_by_real_saves(
    preparer: PostPreparer, *, recordless: bool
) -> None:
    first, second = _post('12345678-first'), _post('12345678-second')
    source = _post('source', target=second.id)
    saved_source = _save(preparer, source)
    expected_name = compose_post_directory_name('A post', _NOW, second.id, collision=1)
    expected_folder = f'{_AUTHOR}/{expected_name}'
    if recordless:
        name = compose_post_directory_name('A post', _NOW, first.id)
        (preparer.library_root / _AUTHOR / name).mkdir()
        preparer = replace(preparer, store=JsonPostStore(preparer.library_root))
    page = preparer.library_root / saved_source.folder / 'post.html'
    page.write_bytes(
        prepare_post_page(
            saved_source.record,
            folder=saved_source.folder,
            link_resolver=_FixedTarget(second.id, expected_folder),
        ).content
    )
    before = _snapshot(preparer.library_root)

    plan = _plan(preparer, [source, first, second])

    assert plan.new_posts == 2
    assert plan.updated_posts == 0
    assert plan.unchanged_posts == 1
    assert _snapshot(preparer.library_root) == before
    _save(preparer, first)
    assert _save(preparer, second).folder == expected_folder
    _save(preparer, source)
    assert _snapshot(preparer.library_root)[page] == before[page]


def test_reservations_use_the_real_folder_policy_without_creating_paths(
    preparer: PostPreparer,
) -> None:
    locator = ReservedPostLocator(preparer.store)
    planning = replace(preparer, store=locator)
    first = planning.prepare(_post('12345678-first'), _FILTERS, _NOW)
    locator.reserve(first.live.post, first.folder)
    second = planning.prepare(_post('12345678-second'), _FILTERS, _NOW)

    assert first.folder != second.folder
    assert '[2]' in second.folder
    assert not preparer.library_root.exists()


@pytest.mark.parametrize(
    ('first_title', 'second_title'),
    [('Lesson', 'lesson'), ('Caf\u00e9', 'Cafe\u0301')],
)
def test_new_reservations_treat_case_and_unicode_variants_as_the_same_folder(
    preparer: PostPreparer, first_title: str, second_title: str
) -> None:
    locator = ReservedPostLocator(preparer.store)
    planning = replace(preparer, store=locator)
    first = planning.prepare(_post('12345678-first', title=first_title), _FILTERS, _NOW)
    locator.reserve(first.live.post, first.folder)

    second = planning.prepare(
        _post('12345678-second', title=second_title), _FILTERS, _NOW
    )

    assert '[2]' in second.folder
    assert not preparer.library_root.exists()


def test_existing_canonical_case_variants_keep_their_saved_locations(
    preparer: PostPreparer,
) -> None:
    store = MemoryPostStore()
    first = preparer.prepare(_post('first'), _FILTERS, _NOW).reconciliation.record
    second = preparer.prepare(_post('second'), _FILTERS, _NOW).reconciliation.record
    assert first is not None
    assert second is not None
    store.save_post('writer/Lesson', first)
    store.save_post('writer/lesson', second)
    locator = ReservedPostLocator(store)
    locator.reserve(first.post, 'writer/Lesson')

    located = locator.find_post(_AUTHOR, second.post.id)

    assert located is not None
    assert located.record is not None
    assert located.folder == 'writer/lesson'
    assert located.record.post.id == second.post.id


def test_a_recordless_decomposed_folder_cannot_be_claimed_by_two_full_ids(
    preparer: PostPreparer,
) -> None:
    first = preparer.prepare(_post('12345678-first', title='Caf\u00e9'), _FILTERS, _NOW)
    decomposed_folder = unicodedata.normalize('NFD', first.folder)
    (preparer.library_root / decomposed_folder).mkdir(parents=True)
    locator = ReservedPostLocator(JsonPostStore(preparer.library_root))
    locator.reserve(first.live.post, first.folder)
    before = _snapshot(preparer.library_root)

    retained = locator.find_post(_AUTHOR, first.live.post.id)
    conflicting = locator.find_post(_AUTHOR, '12345678-second')

    assert retained is not None
    assert retained.record is None
    assert conflicting is None
    assert _snapshot(preparer.library_root) == before


def test_repeating_a_target_keeps_the_final_link_and_unique_plan_counts(
    preparer: PostPreparer,
) -> None:
    source, target = _post('source', target='target'), _post('target')
    saved_source = _save(preparer, source)
    expected_folder = preparer.prepare(target, _FILTERS, _NOW).folder
    page = preparer.library_root / saved_source.folder / 'post.html'
    page.write_bytes(
        prepare_post_page(
            saved_source.record,
            folder=saved_source.folder,
            link_resolver=_FixedTarget(target.id, expected_folder),
        ).content
    )
    before = _snapshot(preparer.library_root)

    plan = _plan(preparer, [source, target, target, source])

    assert plan.new_posts == 1
    assert plan.unchanged_posts == 1
    assert plan.updated_posts == 0
    assert _snapshot(preparer.library_root) == before
    assert _save(preparer, target).folder == expected_folder
    assert _save(preparer, target).folder == expected_folder
    _save(preparer, source)
    assert _snapshot(preparer.library_root)[page] == before[page]


@pytest.mark.parametrize('first_is_locked', [False, True])
def test_the_first_observation_decides_whether_a_repeated_target_is_selected(
    preparer: PostPreparer, *, first_is_locked: bool
) -> None:
    source, target = _post('source', target='target'), _post('target')
    _save(preparer, source)
    payload = target.model_dump()
    if first_is_locked:
        payload['has_access'] = False
    else:
        payload['tags'] = [{'id': 1, 'title': 'skip'}]
    unavailable_target = PostDTO.model_validate(payload)
    before = _snapshot(preparer.library_root)

    plan = _plan(
        preparer, [source, unavailable_target, target], excluded_tags=('skip',)
    )

    assert plan.new_posts == 0
    assert plan.updated_posts == 0
    assert plan.unchanged_posts == 1
    assert plan.excluded_posts == (0 if first_is_locked else 1)
    assert _snapshot(preparer.library_root) == before


def test_retry_before_the_first_save_reuses_the_reserved_folder(
    preparer: PostPreparer,
) -> None:
    locator = ReservedPostLocator(preparer.store)
    planning = replace(preparer, store=locator)
    post = _post('target')
    first = planning.prepare(post, _FILTERS, _NOW)
    locator.reserve(first.live.post, first.folder)

    retry = planning.prepare(post, _FILTERS, _NOW)

    assert retry.folder == first.folder
    assert retry.stored is None
    assert not preparer.library_root.exists()


def test_a_fresh_canonical_location_takes_precedence_over_an_earlier_reservation(
    preparer: PostPreparer,
) -> None:
    locator = ReservedPostLocator(preparer.store)
    prepared = preparer.prepare(_post('target'), _FILTERS, _NOW)
    locator.reserve(prepared.live.post, prepared.folder)
    saved = _save(preparer, _post('target', title='A different saved title'))

    located = locator.find_post(_AUTHOR, 'target')

    assert located is not None
    assert located.record is not None
    assert located.folder == saved.folder
    assert located.folder != prepared.folder
