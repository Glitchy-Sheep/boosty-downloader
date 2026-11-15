"""Plan portable folders for a confirmed new library without creating storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.domain.post_folder import (
    compose_post_directory_name,
    get_post_id_prefix,
)
from boosty_downloader.infrastructure.library._db_post_paths import (
    author_directory,
    path_is_occupied,
    portable_path_key,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from boosty_downloader.domain.library import LocatedPost
    from boosty_downloader.domain.stored_post import PostMetadata


class EmptyPostLocator:
    """Keep an empty saved-record snapshot and respect current occupied folder names."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Validate a portable identity absent from this new library's snapshot."""
        author_directory(self._root, author)
        get_post_id_prefix(post_id)
        return None

    def choose_post_folder(
        self, post: PostMetadata, *, reserved_folders: Collection[str] = ()
    ) -> str:
        """Use the canonical folder policy without allocating directories or records."""
        directory = author_directory(self._root, post.author)
        reserved = {portable_path_key(folder) for folder in reserved_folders}
        collision = 0
        while True:
            name = compose_post_directory_name(
                post.title, post.created_at, post.id, collision=collision
            )
            relative = f'{post.author}/{name}'
            if portable_path_key(relative) not in reserved and not path_is_occupied(
                directory / name
            ):
                return relative
            collision += 1
