"""An in-memory PostStore for tests that need records without filesystem access."""

from copy import deepcopy
from dataclasses import dataclass

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    PostMetadata,
    StoredPost,
)


@dataclass(frozen=True, slots=True)
class _PostKey:
    author: str
    post_id: str


class MemoryPostStore:
    """Keep independent record snapshots and separate observations of lost access."""

    def __init__(self) -> None:
        self._posts: dict[_PostKey, LocatedPost] = {}
        self._authors: dict[str, AuthorInfo] = {}
        self._locked_posts: dict[_PostKey, LockedPost] = {}

    def seed_post_folder(self, author: str, post_id: str, folder: str) -> None:
        """Represent an existing folder without creating or replacing a record."""
        key = _PostKey(author, post_id)
        self._check_folder(key, folder)
        self._posts.setdefault(key, LocatedPost(folder))

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Load an independent snapshot of the folder and any surviving record."""
        return deepcopy(self._posts.get(_PostKey(author, post_id)))

    def choose_post_folder(self, post: PostMetadata) -> str:
        """Choose a deterministic fixture path without reserving it."""
        return f'{post.author}/{post.id}'

    def save_post(self, folder: str, record: StoredPost) -> None:
        """Save a record snapshot in its own folder, preserving access observations."""
        key = _PostKey(record.post.author, record.post.id)
        self._check_folder(key, folder)
        self._posts[key] = LocatedPost(folder, deepcopy(record))

    def save_author(self, author: AuthorInfo) -> None:
        """Keep an independent copy of the author's information."""
        self._authors[author.author] = deepcopy(author)

    def save_locked_post(self, post: LockedPost) -> None:
        """Record lack of access without changing the saved body or its folder."""
        key = _PostKey(post.post.author, post.post.id)
        self._locked_posts[key] = deepcopy(post)

    def clear_locked_post(self, author: str, post_id: str) -> None:
        """Clear only the observation of lost access, if one exists."""
        self._locked_posts.pop(_PostKey(author, post_id), None)

    def _check_folder(self, key: _PostKey, folder: str) -> None:
        existing = self._posts.get(key)
        if existing is not None and existing.folder != folder:
            message = f'Post {key.post_id} already belongs to folder {existing.folder}'
            raise ValueError(message)
        occupied = any(
            location.folder == folder and owner != key
            for owner, location in self._posts.items()
        )
        if occupied:
            message = f'Folder {folder} belongs to another post'
            raise ValueError(message)
