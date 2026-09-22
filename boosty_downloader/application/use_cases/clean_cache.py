"""Use case: forget everything the cache knows about one creator."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from boosty_downloader.application.ports import CacheStorage


class CleanCacheOutcome(Enum):
    """What the clean-cache run found and did."""

    nothing_to_clean = 'nothing_to_clean'
    cancelled = 'cancelled'
    cleaned = 'cleaned'


class CleanCacheUseCase:
    """
    Removes the creator's cache so the next download starts from scratch.

    The cache is the only record of what was downloaded, so the caller
    confirms before it goes. Works on the files only: opening the
    database would create it and turn a missing cache into a false success.
    """

    def __init__(self, storage: CacheStorage, *, confirm: Callable[[], bool]) -> None:
        self.storage = storage
        self.confirm = confirm

    def execute(self) -> CleanCacheOutcome:
        if not self.storage.exists():
            return CleanCacheOutcome.nothing_to_clean
        if not self.confirm():
            return CleanCacheOutcome.cancelled
        self.storage.remove()
        return CleanCacheOutcome.cleaned
