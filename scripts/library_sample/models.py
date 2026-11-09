"""Named inputs and results for synthetic library generation."""

from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path

from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost, StoredPost
from library_sample.asset_models import AssetBackend

MAX_SEED = 0xFFFFFFFF


class AuthorName(str, Enum):
    """Stable names of the three approved synthetic blogs."""

    devlog = 'pixel_forge'
    music = 'sound_garden'
    art = 'sketchbook_lena'


class Scenario(IntEnum):
    """Reserved ordinals in every author's compact corpus."""

    all_kinds = 0
    text_only = 1
    locked_teaser = 2
    locked_no_teaser = 3
    attachments = 4
    local_states = 5
    lost_access = 6
    updated_since_seen = 7


@dataclass(frozen=True, slots=True)
class SampleConfig:
    """Repeatable content seed and exact number of distinct post identities."""

    seed: int = 7
    posts: int = 1430

    def __post_init__(self) -> None:
        """Validate dimensions before the generator performs any writes."""
        if type(self.seed) is not int or not 0 <= self.seed <= MAX_SEED:
            message = 'seed must be an unsigned 32-bit integer'
            raise ValueError(message)
        if type(self.posts) is not int or self.posts <= 0:
            message = 'posts must be a positive integer'
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class AssetPlacement:
    """An immutable asset copied to a portable owner-relative path."""

    relative_path: str
    source: Path


@dataclass(frozen=True, slots=True)
class SampleAuthor:
    """Author metadata and files relative to its author folder."""

    info: AuthorInfo
    files: tuple[AssetPlacement, ...]


@dataclass(frozen=True, slots=True)
class SamplePost:
    """One identity, with optional retained body and current access observation."""

    record: StoredPost | None
    locked: LockedPost | None
    marks: PostMarks | None
    files: tuple[AssetPlacement, ...]

    def __post_init__(self) -> None:
        """Keep access and retained-content identities consistent."""
        if self.record is None:
            if self.locked is None or self.marks is not None or self.files:
                message = (
                    'A locked-only post has an observation and no saved files or marks'
                )
                raise ValueError(message)
        elif self.locked is not None and (
            self.record.post.author != self.locked.post.author
            or self.record.post.id != self.locked.post.id
        ):
            message = 'Saved and locked content must describe the same identity'
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class SampleDescription:
    """Completed generated corpus and its resolved asset backend."""

    root: Path
    config: SampleConfig
    backend: AssetBackend
    authors: int
    posts: int
    saved_posts: int
    locked_posts: int
    media: int
