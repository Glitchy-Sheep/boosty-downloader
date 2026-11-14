"""Storage-neutral identities, snapshots and progress for user mark changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boosty_downloader.domain.library import LibraryAuthor, PostRow


@dataclass(frozen=True, slots=True)
class PostMarkResult:
    """Fresh post state and author totals after a successful mark update."""

    post: PostRow
    author: LibraryAuthor


@dataclass(frozen=True, slots=True)
class BulkMarkProgress:
    """Selected posts, completed updates and actual canonical mark changes."""

    total: int
    completed: int
    changed: int
