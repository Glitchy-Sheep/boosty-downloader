"""Reserve portable post locations consistently for previews and real runs."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING
from unicodedata import normalize

from boosty_downloader.domain.library import LocatedPost, PostIdentity

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from boosty_downloader.application.ports import PostLocator
    from boosty_downloader.domain.stored_post import PostMetadata


def _folder_key(folder: str) -> str:
    return normalize('NFC', folder).casefold()


class _ReservedFolderView(Collection[str]):
    """Check portable path equivalence without copying the growing reservations."""

    def __init__(
        self,
        owners: Mapping[str, PostIdentity],
        additional: Collection[str] = (),
    ) -> None:
        self._owners = owners
        self._additional = frozenset(_folder_key(folder) for folder in additional)

    def __contains__(self, folder: object) -> bool:
        if not isinstance(folder, str):
            return False
        key = _folder_key(folder)
        return key in self._owners or key in self._additional

    def __iter__(self) -> Iterator[str]:
        yield from self._owners
        yield from (key for key in self._additional if key not in self._owners)

    def __len__(self) -> int:
        return len(self._owners) + sum(
            key not in self._owners for key in self._additional
        )


class ReservedPostLocator:
    """Keep new folders distinct across case and Unicode variants within a run."""

    def __init__(self, locator: PostLocator) -> None:
        self._locator = locator
        self._owners: dict[str, PostIdentity] = {}
        self._folders: dict[PostIdentity, str] = {}
        self._reservations = _ReservedFolderView(self._owners)

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Keep canonical locations; reuse recordless folders only for their owner."""
        located = self._locator.find_post(author, post_id)
        if located is not None and located.record is not None:
            return located
        identity = PostIdentity(author, post_id)
        reserved = self._folders.get(identity)
        if reserved is not None:
            return LocatedPost(reserved)
        if located is not None:
            owner = self._owners.get(_folder_key(located.folder))
            if owner is not None and owner != identity:
                return None
        return located

    def choose_post_folder(
        self, post: PostMetadata, *, reserved_folders: Collection[str] = ()
    ) -> str:
        """Apply portable reservations to the storage adapter's folder choices."""
        reservations = self._reservations
        if reserved_folders:
            reservations = _ReservedFolderView(self._owners, reserved_folders)
        return self._locator.choose_post_folder(post, reserved_folders=reservations)

    def reserve(self, post: PostMetadata, folder: str) -> None:
        """Keep a successfully prepared post's folder for the rest of this run."""
        identity = PostIdentity(post.author, post.id)
        self._owners[_folder_key(folder)] = identity
        self._folders[identity] = folder
