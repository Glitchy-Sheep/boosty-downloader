"""Filesystem observations shared by media planning and storage adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Set as AbstractSet


@dataclass(frozen=True, slots=True)
class DiskSnapshot:
    """Regular-file byte sizes and occupied non-file names, using post-relative POSIX paths."""

    files: Mapping[str, int]
    occupied: AbstractSet[str] = field(default_factory=frozenset[str])
    # Queried spelling -> actual path, only when the filesystem confirms it.
    aliases: Mapping[str, str] = field(default_factory=dict[str, str])
