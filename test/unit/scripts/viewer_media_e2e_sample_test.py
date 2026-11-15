"""Browser fixtures use real storage, index membership and portable playable assets."""

import os
from pathlib import Path

import pytest
from viewer_media_e2e_sample import AUTHOR, EQUAL, GALLERY, REMOVED, post_id, prepare

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.library_media import LibraryMediaView, MediaFilters
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader
from boosty_downloader.infrastructure.raster_headers import inspect_raster_header


def test_media_corpus_covers_retained_missing_locked_and_individual_playback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / 'media'
    link = os.link
    sources: list[Path] = []

    def link_within_corpus(source: Path, destination: Path) -> None:
        assert source.is_relative_to(root)
        sources.append(source)
        link(source, destination)

    monkeypatch.setattr('viewer_media_e2e_sample.os.link', link_within_corpus)
    prepare(root, photos=30)
    assert any(source.suffix == '.jpg' for source in sources)
    reader = JsonLibraryReader(root)
    page = reader.list_media(AUTHOR, LibraryMediaView.all, MediaFilters())
    assert len(page.items) == 48
    assert page.missing == 18
    assert page.posts[post_id(5)].access is PostAccess.locked
    split = next(
        index for index, item in enumerate(page.items) if item.entry.removed_at
    )
    assert all(item.entry.removed_at for item in page.items[split:])
    unseen = reader.list_media(
        AUTHOR, LibraryMediaView.audio, MediaFilters(unseen_only=True)
    )
    assert all(item.post_id != post_id(3) for item in unseen.items)
    assert any(item.post_id == post_id(4) for item in unseen.items)
    assert all(
        not item.playback or not item.playback.finished_at for item in unseen.items
    )
    removed = reader.list_media(REMOVED, LibraryMediaView.all, MediaFilters())
    assert len(removed.items) == 8
    assert all(item.entry.removed_at for item in removed.items)
    assert removed.missing == 0
    gallery = reader.list_media(GALLERY, LibraryMediaView.image, MediaFilters())
    assert len(gallery.items) == 30
    assert all(
        item.thumbnail_path and (root / item.thumbnail_path).is_file()
        for item in gallery.items
    )
    assert len({item.thumbnail_path for item in gallery.items}) == 30
    for item in gallery.items[:3]:
        assert item.thumbnail_path
        thumbnail = root / item.thumbnail_path
        header = inspect_raster_header(thumbnail.read_bytes())
        assert header.extension == '.jpg'
        assert header.width == 480
        assert header.height >= 270
        assert thumbnail.stat().st_size > 5000
        assert item.entry.path
        original = root / item.folder / item.entry.path
        assert original.stat().st_size > 3_000_000
    current_counts = {LibraryMediaView.image: 8, LibraryMediaView.video: 2}
    for view, current in current_counts.items():
        equal = reader.list_media(EQUAL, view, MediaFilters())
        assert len(equal.items) == 14
        assert equal.missing == 1
        assert sum(not item.entry.removed_at for item in equal.items) == current
