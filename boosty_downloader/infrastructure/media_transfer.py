"""A persisted destination shared by media transports and the post owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaTarget:
    """A concrete reserved path whose pending record has already been saved."""

    library_root: Path
    post_folder: str
    relative_path: str
    media_id: str


ReserveMediaPath: TypeAlias = 'Callable[[str], MediaTarget]'
