"""clean-cache must report honestly: nothing to clean vs cleaned, and never touch a missing cache."""

from __future__ import annotations

from boosty_downloader.application.use_cases.clean_cache import (
    CleanCacheOutcome,
    CleanCacheUseCase,
)


class _FakeStorage:
    def __init__(self, *, present: bool) -> None:
        self._present = present
        self.removed = 0

    def exists(self) -> bool:
        return self._present

    def remove(self) -> None:
        self.removed += 1
        self._present = False


def test_missing_cache_is_reported_and_left_alone():
    """The old command opened the database first, which created it and faked a success."""
    storage = _FakeStorage(present=False)
    assert CleanCacheUseCase(storage).execute() is CleanCacheOutcome.nothing_to_clean
    assert storage.removed == 0


def test_existing_cache_is_removed_once():
    storage = _FakeStorage(present=True)
    assert CleanCacheUseCase(storage).execute() is CleanCacheOutcome.cleaned
    assert storage.removed == 1
    # A second run finds nothing: the promise "fresh start" is kept, not repeated.
    assert CleanCacheUseCase(storage).execute() is CleanCacheOutcome.nothing_to_clean
