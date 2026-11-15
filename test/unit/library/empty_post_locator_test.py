from dataclasses import replace
from pathlib import Path

import pytest
from support.library_db import NOW

from boosty_downloader.domain.stored_post import PostMetadata
from boosty_downloader.infrastructure.library.empty_post_locator import EmptyPostLocator


def test_empty_locator_uses_canonical_folders_and_portable_reservations(tmp_path: Path):
    root = tmp_path.resolve() / 'missing'
    locator = EmptyPostLocator(root)
    post = PostMetadata(
        '12345678-full', 'alice', 'https://boosty.to/alice', 'Title', NOW, NOW
    )
    first = 'alice/2026-10-01 - Title (12345678)'
    second = 'alice/2026-10-01 - Title [2] (12345678)'
    assert locator.find_post(post.author, post.id) is None
    assert locator.choose_post_folder(post) == first
    assert locator.choose_post_folder(post, reserved_folders=[first.upper()]) == second
    assert not root.exists()
    (root / first).mkdir(parents=True)
    assert locator.choose_post_folder(post, reserved_folders=[second]) == (
        'alice/2026-10-01 - Title [3] (12345678)'
    )


@pytest.mark.parametrize('author', ['../outside', '', 'CON'])
def test_empty_locator_rejects_unsafe_author_identities(tmp_path: Path, author: str):
    locator = EmptyPostLocator(tmp_path.resolve() / 'missing')
    post = PostMetadata(
        '12345678-full', 'alice', 'https://boosty.to/alice', 'Title', NOW, NOW
    )
    with pytest.raises(ValueError, match='Author'):
        locator.find_post(author, post.id)
    with pytest.raises(ValueError, match='Author'):
        locator.choose_post_folder(replace(post, author=author))
    assert list(tmp_path.iterdir()) == []
