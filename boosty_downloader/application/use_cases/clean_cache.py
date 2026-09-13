"""Use case: forget everything the cache knows about one creator."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boosty_downloader.application.ports import CacheStorage


class CleanCacheOutcome(Enum):
    """What the clean-cache run found and did."""

    nothing_to_clean = 'nothing_to_clean'
    cleaned = 'cleaned'


class CleanCacheUseCase:
    """
    Removes the creator's cache so the next download starts from scratch.

    Works on the files only: opening the database would create it and
    turn a missing cache into a false success.
    """

    def __init__(self, storage: CacheStorage) -> None:
        self.storage = storage

    def execute(self) -> CleanCacheOutcome:
        if not self.storage.exists():
            return CleanCacheOutcome.nothing_to_clean
        self.storage.remove()
        return CleanCacheOutcome.cleaned
